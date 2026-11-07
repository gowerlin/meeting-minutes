#!/usr/bin/env node
// meeting-minutes 公開 repo 的去識別掃描。零依賴（以 Control Tower Portal 的 deid-scan.mjs 為底改寫）。
//
//   node scripts/deid-scan.mjs [--terms <私有詞表>] [--allow <允許清單>] [--internal-ids] <路徑…>
//
// 詞表與允許清單放在 repo 外（不進公開 repo），以參數或環境變數 MM_DEID_TERMS／MM_DEID_ALLOW 傳入（參數優先）；
// 兩個都沒有就報錯結束（exit 2），不會略過掃描。
//
// 只輸出「檔案:行:類別」與各類計數，不輸出命中的原文（避免把敏感值印進日誌）。命中數 > 0 時 exit 1。
//
// 掃描範圍：
//   - EXTENSIONS 的副檔名，以及沒有副檔名的檔案（含 .gitignore 這類點開頭的檔名）；前 8 KB 有 NUL 位元組的視為二進位，跳過
//   - .zip 一律在記憶體裡解開再掃（含 zip 裡的 zip），命中寫成「<zip 路徑>!<zip 內路徑>:行:類別」
//   - 不掃 SKIP_DIRS 的目錄；dist 只有直接當參數傳入時才掃（例 .vitepress/dist）
//
// --internal-ids：內部編號類別（工單號、決策號、BUG／PLAN／EXP、本地規則代號、驗收條件號、內部標記、工作目錄名）
// 對所有掃描的檔案生效，包括程式與測試。沒有範例編號的例外。HTML 先去掉標籤；建置產物先遮掉 Vite 產物雜湊。
//
// 私有詞表格式：一行一詞，`#` 開頭是註解；可以加類別欄（「類別<Tab>詞」）。比對不分大小寫。
// 允許清單格式：一行一項，`#` 開頭是註解。
//   - 一般項目（例如公開 repo 的帳號名、網址）：只允許寫在 .vitepress/ 的設定、建置產物與公開 repo 根目錄的
//     README.md、LICENSE、THIRD-PARTY-NOTICES.md；寫在其他檔案記為「允許清單項目寫在設定以外」
//   - 「anywhere<Tab>項目」：任何檔案都放行（例如測試裡的 Windows 系統目錄、Git Bash 預設安裝路徑這類非個資的系統路徑）
//   比對前先把這一行的允許項目拿掉（長的先比），其餘類別照舊比對。

import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { fileURLToPath } from 'node:url'

const EXTENSIONS = new Set([
  '.md', '.vue', '.ts', '.mts', '.css', '.json', '.jsonl', '.html', '.svg', '.js', '.mjs', '.toml', '.txt', '.srt', '.xml', '.yml', '.yaml',
  '.py', '.ps1', '.sh', '.cmd', '.command', '.tsv', '.cfg', '.ini', '.csv'
])
// 不掃的目錄：依賴、建置快取、本機產物（測試輸出、venv、分析工具快取）。dist 要另外當路徑參數傳入才掃
const SKIP_DIRS = new Set(['node_modules', '.git', 'cache', '__pycache__', '_out', 'venv', '.venv', '.sonar'])
const SKIP_UNLESS_ROOT = new Set(['dist'])
// 不掃的檔案：鎖檔只有套件名稱與雜湊；規劃文件不公開，而且本身就列出這裡的正則
const SKIP_FILES = new Set(['package-lock.json', 'PORTAL-PLAN.md'])

const PATTERNS = [
  ['1-專案名', /\b20[0-9]{2}_[A-Za-z][A-Za-z0-9_-]+/g],
  ['3-個人路徑', /([A-Z]:[\\/]+|\/[a-z]\/)Users[\\/]/gi],
  ['3-磁碟路徑', /\b[A-Z]:[\\/]+[A-Za-z@]/g],
  ['3-家目錄路徑', /(^|[^\w.~-])\/(?:Users|home)\/[\w.-]/g],
  ['3-專案目錄編碼', /[A-Za-z]--[A-Za-z0-9-]+--/g],
  ['3-Claude 專案目錄', /\.claude[\\/]projects[\\/]/g],
  // 10. 開頭要四段：規格的章節號（例 10.2.1）不算
  ['4-內網位址', /\b(?:10(?:\.[0-9]{1,3}){3}|(?:192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))(?:\.[0-9]{1,3}){2})\b/g],
  // hf_ 只認 30 碼以上不含底線的字串：hf_hub_download 這類識別字不算
  ['5-權杖', /(?:ghp_|gho_|github_pat_|sk-ant-|sk-proj-|glpat-|AKIA|xox[bp]-)[A-Za-z0-9_-]{8,}|\bhf_[A-Za-z0-9]{30,}/g],
  ['6-UUID', /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi],
  ['6-32 碼 hex', /\b[0-9a-f]{32}\b/g],
  ['7-私人規則名', /R-G0[0-9]{2}/g],
  ['8-Email', /[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[a-z]{2,})/g]
]
const EMAIL_ALLOWED = /(^|\.)example\.(com|org|net)$/

// 內部編號（--internal-ids）。正則刻意寫成不會命中這支腳本自己的形式（例：用字元類別拆開字面字串）
const INTERNAL_PATTERNS = [
  ['內部 id-工單號', /\bT[0-9]{4}\b|\bT#{4}(?!#)|\bCT-T[0-9]{3}\b/g],
  ['內部 id-決策號', /\bD[0-9]{2,3}\b|\bD#{3}(?!#)/g],
  ['內部 id-BUG／PLAN／EXP', /\b(?:BUG|PLAN|EXP)-[0-9]{3}\b/g],
  ['內部 id-本地規則', /\bLR-[0-9]{3}\b/g],
  ['內部 id-驗收條件', /\bAC-[0-9]+\b/g],
  ['內部 id-內部標記', /〔(?:實作|本單|裁定|塔[台])[^〕\n]*〕/g],
  ['內部 id-工作目錄', /_ct[-]workorders/g],
  ['內部 id-內部角色名', /塔[台]/g],
  // 後面接 .md 的是排除清單裡的檔名（功能性的，放行）
  ['內部 id-規劃文件', /PORTAL[-]PLAN(?!\.md)/g]
]

// HTML 去標籤：標籤換成空白，不跨行，行號不變；註解只拿掉 <!-- 與 -->，內文照樣比對
const stripTags = text => text.replace(/<!--|-->/g, ' ').replace(/<[^>\n]*>/g, ' ')

// Vite 產物雜湊（檔名「<名稱>.<8 碼>.js」、頁面雜湊表「"<頁>.md":"<8 碼>"」）可能剛好長得像編號，比對內部編號前換成同長度底線
const VITE_HASHED_NAME = /(\.)[A-Za-z0-9_-]{8}(?=\.(?:lean\.)?(?:js|mjs|css)\b)/g
const VP_HASH_MAP_ENTRY = /(\.md\\?":\\?")[A-Za-z0-9_-]{8}(?=\\?")/g
const maskHash = (match, prefix) => prefix + '_'.repeat(match.length - prefix.length)
const maskViteHashes = text => text.replace(VITE_HASHED_NAME, maskHash).replace(VP_HASH_MAP_ENTRY, maskHash)

function usage(message) {
  if (message) console.error(`deid-scan: ${message}`)
  console.error('用法：node scripts/deid-scan.mjs [--terms <私有詞表>] [--allow <允許清單>] [--internal-ids] <路徑…>')
  console.error('      沒給 --terms／--allow 時讀環境變數 MM_DEID_TERMS／MM_DEID_ALLOW')
  process.exit(2)
}

function parseArgs(argv) {
  const env = name => process.env[name] || null
  const out = { terms: env('MM_DEID_TERMS'), allow: env('MM_DEID_ALLOW'), internalIds: false, paths: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--terms') out.terms = argv[++i]
    else if (a === '--allow') out.allow = argv[++i]
    else if (a === '--internal-ids') out.internalIds = true
    else if (a.startsWith('--')) usage(`不認得的參數 ${a}`)
    else out.paths.push(a)
  }
  if (!out.terms) usage('沒有私有詞表：請給 --terms 或設定 MM_DEID_TERMS（不帶詞表不掃描）')
  if (!out.allow) usage('沒有允許清單：請給 --allow 或設定 MM_DEID_ALLOW（不帶清單不掃描）')
  if (!out.paths.length) usage('至少給一個要掃的路徑')
  return out
}

function readList(file) {
  if (!fs.existsSync(file)) usage('找不到詞表或允許清單（路徑不印出）')
  return fs
    .readFileSync(file, 'utf8')
    .split(/\r?\n/)
    .map(line => line.replace(/\s+$/, ''))
    .filter(line => line.trim() && !line.trim().startsWith('#'))
}

function loadTerms(file) {
  return readList(file).map(line => {
    const [first, second] = line.split('\t')
    const term = second === undefined ? first : second
    const category = second === undefined ? '1' : first.trim()
    const escaped = term.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return { category: `${category}-私有詞表`, re: new RegExp(escaped, 'gi') }
  })
}

// 長的項目先比對：較短的項目先從這一行拿掉的話，含它的較長項目就比對不到
function loadAllow(file) {
  return readList(file)
    .map(line => {
      const m = line.match(/^anywhere\t(.+)$/)
      return m ? { entry: m[1].trim(), anywhere: true } : { entry: line.trim(), anywhere: false }
    })
    .filter(a => a.entry)
    .sort((a, b) => b.entry.length - a.entry.length)
}

export function isScannable(file) {
  const ext = path.extname(file).toLowerCase()
  return ext === '' || EXTENSIONS.has(ext)
}

const isBinaryBuffer = buf => buf.subarray(0, 8192).includes(0)
const posix = p => p.split(path.sep).join('/')

// ---------- zip（只讀 central directory；支援 stored 與 deflate） ----------

function readZip(buf) {
  let eocd = -1
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65557); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('不是 zip（找不到 end of central directory）')
  const count = buf.readUInt16LE(eocd + 10)
  let p = buf.readUInt32LE(eocd + 16)
  const entries = []
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error('zip central directory 損壞')
    const method = buf.readUInt16LE(p + 10)
    const csize = buf.readUInt32LE(p + 20)
    const nameLen = buf.readUInt16LE(p + 28)
    const extraLen = buf.readUInt16LE(p + 30)
    const commentLen = buf.readUInt16LE(p + 32)
    const local = buf.readUInt32LE(p + 42)
    const name = buf.subarray(p + 46, p + 46 + nameLen).toString('utf8')
    p += 46 + nameLen + extraLen + commentLen
    if (name.endsWith('/')) continue
    const lNameLen = buf.readUInt16LE(local + 26)
    const lExtraLen = buf.readUInt16LE(local + 28)
    const start = local + 30 + lNameLen + lExtraLen
    const raw = buf.subarray(start, start + csize)
    let data
    if (method === 0) data = raw
    else if (method === 8) data = zlib.inflateRawSync(raw)
    else throw new Error(`zip 內 ${name} 用了不支援的壓縮方式 ${method}`)
    entries.push({ name, data })
  }
  return entries
}

// ---------- 收集要掃的內容 ----------

// item：{ label（輸出用的路徑）, file（實體檔，判斷設定檔與根目錄檔用；zip 內容是 zip 本身的路徑）, inZip, text }
function collect(target, isRoot, out, skipped) {
  const stat = fs.statSync(target)
  if (stat.isFile()) {
    const base = path.basename(target)
    if (SKIP_FILES.has(base)) return
    if (path.extname(base).toLowerCase() === '.zip') {
      collectZip(posix(target), target, fs.readFileSync(target), out, skipped)
      return
    }
    if (!isScannable(target)) return
    const buf = fs.readFileSync(target)
    if (isBinaryBuffer(buf)) return
    out.push({ label: posix(target), file: target, inZip: false, text: buf.toString('utf8') })
    return
  }
  const name = path.basename(target)
  if (!isRoot && (SKIP_DIRS.has(name) || SKIP_UNLESS_ROOT.has(name))) return
  for (const entry of fs.readdirSync(target)) collect(path.join(target, entry), false, out, skipped)
}

function collectZip(label, file, buf, out, skipped) {
  let entries
  try {
    entries = readZip(buf)
  } catch (e) {
    skipped.push(`${label}（${e.message}）`)
    return
  }
  for (const { name, data } of entries) {
    const inner = `${label}!${name}`
    if (name.toLowerCase().endsWith('.zip')) collectZip(inner, file, data, out, skipped)
    else if (isScannable(name) && !isBinaryBuffer(data)) out.push({ label: inner, file, inZip: true, text: data.toString('utf8') })
  }
}

// ---------- 允許清單的「設定以外」判斷 ----------

function isBuildOutput(file) {
  return /(^|\/)\.vitepress\/dist\//.test(posix(path.resolve(file)))
}

function isConfig(file) {
  return /(^|\/)\.vitepress\/[^/]+\.(mts|ts|json)$/.test(posix(path.resolve(file)))
}

// 公開 repo 根目錄的 README.md、LICENSE、THIRD-PARTY-NOTICES.md：要寫 Portal 網址與著作權人的帳號名。
// 「根目錄」＝旁邊有 site/.vitepress/config.mts（公開 repo 的根），或本機來源 site/repo-root/（旁邊的上一層有 .vitepress/config.mts）
const ROOT_FILES = new Set(['README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md'])

function isRepoRootFile(file) {
  const abs = path.resolve(file)
  if (!ROOT_FILES.has(path.basename(abs))) return false
  const dir = path.dirname(abs)
  if (fs.existsSync(path.join(dir, 'site', '.vitepress', 'config.mts'))) return true
  return path.basename(dir) === 'repo-root' && fs.existsSync(path.join(dir, '..', '.vitepress', 'config.mts'))
}

const allowedPlace = item => !item.inZip && (isBuildOutput(item.file) || isConfig(item.file) || isRepoRootFile(item.file))

function main() {
  const args = parseArgs(process.argv.slice(2))
  const terms = loadTerms(args.terms)
  const allow = loadAllow(args.allow)
  const items = []
  const skipped = []
  for (const p of args.paths) {
    if (!fs.existsSync(p)) usage(`找不到 ${p}`)
    collect(p, true, items, skipped)
  }

  const counts = new Map()
  const hits = []
  const add = (item, line, category) => {
    hits.push(`${item.label}:${line}:${category}`)
    counts.set(category, (counts.get(category) || 0) + 1)
  }

  for (const item of items) {
    const lines = item.text.split(/\r?\n/)
    let internalLines = []
    if (args.internalIds) {
      let t = item.label.endsWith('.html') ? stripTags(item.text) : item.text
      if (isBuildOutput(item.file)) t = maskViteHashes(t)
      internalLines = t.split(/\r?\n/)
    }
    const okPlace = allowedPlace(item)
    lines.forEach((raw, i) => {
      let line = raw
      let internal = internalLines[i] ?? ''
      for (const { entry, anywhere } of allow) {
        if (!line.includes(entry)) continue
        if (!anywhere && !okPlace) add(item, i + 1, '允許清單項目寫在設定以外')
        line = line.split(entry).join(' ')
        internal = internal.split(entry).join(' ')
      }
      for (const [category, re] of PATTERNS) {
        for (const m of line.matchAll(re)) {
          if (category === '8-Email' && EMAIL_ALLOWED.test(m[1])) continue
          add(item, i + 1, category)
        }
      }
      for (const { category, re } of terms) {
        for (const _ of line.matchAll(re)) add(item, i + 1, category)
      }
      if (args.internalIds) {
        for (const [category, re] of INTERNAL_PATTERNS) {
          for (const _ of internal.matchAll(re)) add(item, i + 1, category)
        }
      }
    })
  }

  for (const h of hits) console.log(h)
  const zipped = items.filter(i => i.inZip).length
  console.log(
    `deid-scan：掃描 ${items.length} 個檔案（其中 zip 內 ${zipped} 個），命中 ${hits.length}` +
      `${args.internalIds ? '（含內部編號）' : ''}；私有詞表 ${terms.length} 項、允許清單 ${allow.length} 項`
  )
  for (const [category, n] of [...counts].sort()) console.log(`  ${category}: ${n}`)
  if (skipped.length) {
    console.log(`無法解開的 zip（${skipped.length}）：`)
    for (const s of skipped) console.log(`  ${s}`)
  }
  process.exit(hits.length || skipped.length ? 1 : 0)
}

// export-public-repo.mjs import isScannable 時不執行
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()

#!/usr/bin/env node
// 匯出 meeting-minutes 公開 repo 的內容。零依賴（以 Control Tower Portal 的 export-public-repo.mjs 為底改寫）。
//
//   node scripts/export-public-repo.mjs --out <staging 目錄> [--terms <私有詞表>] [--allow <允許清單>]
//   node scripts/export-public-repo.mjs --dry-run [--out <staging 目錄>]    # 只列清單，不寫檔、不掃描
//
//   --ref <git ref>   從這個 commit 匯出（預設 HEAD）：有未 commit 的改動時，匯出的是已 commit 的版本
//   --worktree        改從工作目錄匯出（本機試跑用；推送一律用 --ref）
//
// 來源根目錄是 site/ 的上一層（本機的 meeting-minutes 專案目錄）。路徑對應（左邊是來源，右邊是公開 repo）：
//
//   meeting-minutes-pro-skill/meeting-minutes-pro-v<最新>/**  → pro/meeting-minutes-pro-v<最新>/**
//   meeting-minutes-pro-skill/tests/**                         → pro/tests/**（不含 _out/、__pycache__/、音檔與影片）
//   meeting-minutes-pro-skill/tools/*.py                       → pro/tools/
//   meeting-minutes-skill/meeting-minutes-v<最新>/**           → basic/meeting-minutes-v<最新>/**
//   meeting-minutes-proofread/meeting-minutes-proofread-v<最新>/** → proofread/meeting-minutes-proofread-v<最新>/**（附屬工具「會議記錄校稿」）
//   meeting-minutes-proofread/tests/**                         → proofread/tests/**（不含 _out/、__pycache__/、.sonar/）
//   meeting-minutes-proofread/tools/**                         → proofread/tools/**
//   meeting-minutes-proofread/.gitattributes                   → proofread/.gitattributes（.cmd 要 CRLF）
//   docs/spec/*.md                                             → docs/spec/
//   site/repo-root/**                                          → 根目錄（README.md、LICENSE、THIRD-PARTY-NOTICES.md、
//                                                                .gitignore、.gitattributes、.github/workflows/pages.yml）
//   site/**（SITE_ALLOW 列出的）                                → site/**
//
// 1. 允許清單式複製：只帶上面對應得到的檔案；DENY 一律不帶（DENY 優先）；兩邊都沒列的也不帶，列在「未列入」
// 2. 「最新」＝來源裡版號最高的版本目錄；要和 site/.vitepress/mm-release.json 的 proVersion、basicVersion、proofreadVersion 相同，
//    EXPECTED 列出的檔案也都要在。--dry-run 只把缺項列出來；正式匯出有缺項就停止
// 3. 複製後對 staging 跑 deid-scan.mjs --internal-ids（必須 0；zip 解開掃）。deid-scan 不收的非二進位檔複製成 .txt 補掃
// 4. --out 不得在本 repo 內；已存在時必須是空目錄，或是公開 repo 的 clone（有 .git：除了 .git 全部換成這次匯出的內容，
//    並自動設定 clone 的 core.autocrlf false）
//
// 私有詞表與允許清單以參數或環境變數 MM_DEID_TERMS／MM_DEID_ALLOW 傳入（參數優先），不複製進 staging，路徑也不印出。

import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { isScannable } from './deid-scan.mjs'

const SITE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const ROOT = path.dirname(SITE)

const PRO_PARENT = 'meeting-minutes-pro-skill/'
const PRO_PREFIX = 'meeting-minutes-pro-v'
const BASIC_PARENT = 'meeting-minutes-skill/'
const BASIC_PREFIX = 'meeting-minutes-v'
const PROOFREAD_PARENT = 'meeting-minutes-proofread/'
const PROOFREAD_PREFIX = 'meeting-minutes-proofread-v'

// site/ 底下要帶的：確切檔案、目錄（結尾 /）；頁面 .md 另由 isSitePage 判斷
const SITE_ALLOW_FILES = [
  '.vitepress/config.mts',
  '.vitepress/mm-release.json',
  'scripts/deid-scan.mjs',
  'scripts/export-public-repo.mjs',
  'package.json',
  'package-lock.json',
  '.gitignore',
  'lychee.toml'
]
const SITE_ALLOW_DIRS = ['.vitepress/theme/', 'public/']
const SITE_PAGE_DIRS = ['install/', 'features/', 'usage/', 'design/']

// 一律不帶（來源路徑，相對於來源根目錄；比允許清單優先）。理由寫在清單輸出裡
const DENY = [
  ['site/PORTAL-PLAN.md', '規劃文件，不公開'],
  ['site/node_modules/', '依賴'],
  ['site/.vitepress/cache/', '建置快取'],
  ['site/.vitepress/dist/', '建置產物'],
  [PRO_PARENT + 'research/', '研究原型與原始數據，改寫成網站的研究方法頁'],
  [PRO_PARENT + 'dist/', '打包產物，Release 附件由 make_dist.py 重新產生'],
  [PRO_PARENT + 'tests/_out/', '測試輸出與合成音檔（音檔由講稿重建）'],
  [PROOFREAD_PARENT + 'dist/', '打包產物，Release 附件由 tools/make_dist.py 重新產生'],
  ['spec/', '內部規格原檔；公開版規格放 docs/spec/'],
  ['_ct' + '-workorders/', '內部工單（字串拆開寫：這支腳本本身也會被去識別掃描）']
]
const DENY_ANY_DIR = ['__pycache__/', '.sonar/', 'node_modules/', '_out/', 'venv/']
const DENY_EXT = new Set(['.wav', '.mp3', '.mp4', '.m4a', '.opus', '.flac', '.7z'])

// 必須帶到的檔（公開 repo 的路徑）。{PRO}、{BASIC}、{PROOF} 換成 mm-release.json 的版號
const EXPECTED = [
  ['README.md', 'S1-e'],
  ['LICENSE', 'S1-e'],
  ['THIRD-PARTY-NOTICES.md', 'S1-e'],
  ['.github/workflows/pages.yml', 'S1-e'],
  ['pro/meeting-minutes-pro-v{PRO}/README.md', 'S1-a（Pro 新版）'],
  ['pro/meeting-minutes-pro-v{PRO}/payload/meeting-minutes-pro-upload.zip', 'S1-a（Pro 新版）'],
  ['pro/tests/README.md', 'S1-b（tests 清理）'],
  ['pro/tools/make_dist.py', 'S1-b（tools 清理）'],
  ['basic/meeting-minutes-v{BASIC}/README.md', 'S1-c（基本版新版）'],
  ['basic/meeting-minutes-v{BASIC}/THIRD-PARTY-NOTICES.md', 'S1-c（基本版補 NOTICES）'],
  ['docs/spec/meeting-minutes-pro-2.0-spec.md', 'S1-d（公開版規格）'],
  ['docs/spec/meeting-minutes-pro-2.1-spec.md', '2.1 公開版規格（網頁版）'],
  ['docs/spec/meeting-minutes-pro-2.2-spec.md', '2.2 公開版規格（參考資料、全文用字統一）'],
  ['docs/spec/meeting-minutes-pro-2.3-spec.md', '2.3 公開版規格（配合會議記錄校稿）'],
  ['docs/spec/meeting-minutes-proofread-1.0-spec.md', '會議記錄校稿 1.0 公開版規格'],
  ['docs/spec/meeting-minutes-pro-2.4-spec.md', '2.4 公開版規格（本機限定）'],
  ['docs/spec/meeting-minutes-proofread-1.1-spec.md', '會議記錄校稿 1.1 公開版規格（認得本機限定）'],
  ['docs/spec/meeting-minutes-pro-2.4.1-spec.md', '2.4.1 公開版規格（config.json 讀不了時當成本機限定）'],
  ['docs/spec/meeting-minutes-proofread-1.1.1-spec.md', '會議記錄校稿 1.1.1 公開版規格（同上）'],
  ['docs/spec/meeting-minutes-proofread-1.1.2-spec.md', '會議記錄校稿 1.1.2 公開版規格（影片浮動視窗）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/install.cmd', '會議記錄校稿（Windows 入口）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/install.ps1', '會議記錄校稿（Windows 安裝）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/install.sh', '會議記錄校稿（macOS 安裝）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/uninstall.ps1', '會議記錄校稿（Windows 移除，Pro 2.3 會呼叫）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/uninstall.sh', '會議記錄校稿（macOS 移除，Pro 2.3 會呼叫）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/README.md', '會議記錄校稿（說明）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/LICENSE', '會議記錄校稿（授權）'],
  ['proofread/meeting-minutes-proofread-v{PROOF}/payload/app/mmproof_server.py', '會議記錄校稿（服務）'],
  ['proofread/tests/run_tests.py', '會議記錄校稿（測試）'],
  ['proofread/tools/make_dist.py', '會議記錄校稿（打包）'],
  ['proofread/.gitattributes', '會議記錄校稿（.cmd 的 CRLF）'],
  ['site/install/proofread.md', 'Portal：安裝會議記錄校稿'],
  ['site/features/proofread.md', 'Portal：會議記錄校稿功能頁'],
  ['site/usage/proofread.md', 'Portal：會議記錄校稿使用方法'],
  ['site/features/local-only.md', 'Portal：本機限定（機敏會議）'],
  ['site/package.json', 'S1-e'],
  ['site/index.md', 'S1-e']
]

// deid-scan.mjs 不收的檔案（isScannable 為 false）裡，這些副檔名是二進位，不補掃
const BINARY_EXT = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff', '.woff2', '.zip', '.onnx', '.bin'])

function fail(message) {
  console.error(`[export-public-repo] 錯誤：${message}`)
  process.exit(1)
}

function usage(message) {
  if (message) console.error(`export-public-repo: ${message}`)
  console.error('用法：node scripts/export-public-repo.mjs --out <staging 目錄> [--terms <私有詞表>] [--allow <允許清單>] [--ref <git ref> | --worktree] [--dry-run]')
  process.exit(2)
}

function parseArgs(argv) {
  const env = name => process.env[name] || null
  const out = { out: null, terms: env('MM_DEID_TERMS'), allow: env('MM_DEID_ALLOW'), ref: 'HEAD', worktree: false, dryRun: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--out') out.out = argv[++i]
    else if (a === '--terms') out.terms = argv[++i]
    else if (a === '--allow') out.allow = argv[++i]
    else if (a === '--ref') out.ref = argv[++i]
    else if (a === '--worktree') out.worktree = true
    else if (a === '--dry-run') out.dryRun = true
    else usage(`不認得的參數 ${a}`)
  }
  if (!out.dryRun && !out.out) usage('--out 要給（--dry-run 可省略）')
  if (!out.dryRun && (!out.terms || !out.allow)) usage('不是 --dry-run 時要有私有詞表與允許清單（--terms／--allow 或 MM_DEID_TERMS／MM_DEID_ALLOW；匯出後必須掃描）')
  if (!out.ref) usage('--ref 要給 git ref')
  return out
}

const git = (args, opts = {}) => execFileSync('git', ['-C', ROOT, ...args], { maxBuffer: 256 * 1024 * 1024, ...opts })

// ---------- 來源 ----------

function sourceFromRef(ref) {
  const sha = git(['rev-parse', '--verify', `${ref}^{commit}`], { encoding: 'utf8' }).trim()
  const paths = git(['ls-tree', '-r', '-z', '--name-only', sha, '--', '.'], { encoding: 'utf8' }).split('\0').filter(Boolean)
  const dirty = new Set(git(['diff', '--name-only', '--relative', sha, '--', '.'], { encoding: 'utf8' }).split('\n').filter(Boolean))
  return { label: `git ${ref}（${sha}）`, sha, paths, dirty, read: p => git(['show', `${sha}:./${p}`]) }
}

function sourceFromWorktree() {
  const paths = []
  const walk = rel => {
    for (const entry of fs.readdirSync(path.join(ROOT, rel), { withFileTypes: true })) {
      const p = rel + entry.name
      if (entry.isDirectory()) {
        // 一律不帶的目錄不往下走（tests/_out、node_modules 很大）；清單裡記成一筆
        if (entry.name === '.git' || isDenied(p + '/')) paths.push(p + '/')
        else walk(p + '/')
      } else if (entry.isFile()) paths.push(p)
    }
  }
  walk('')
  return { label: '工作目錄', sha: null, paths, dirty: new Set(), read: p => fs.readFileSync(path.join(ROOT, p)) }
}

// ---------- 分類 ----------

function denyReason(p) {
  const hit = DENY.find(([d]) => (d.endsWith('/') ? p.startsWith(d) : p === d))
  if (hit) return hit[1]
  const dir = DENY_ANY_DIR.find(d => p.startsWith(d) || p.includes('/' + d))
  if (dir) return `本機產物（${dir}）`
  if (DENY_EXT.has(path.extname(p).toLowerCase())) return '音檔、影片或封存檔'
  return null
}
const isDenied = p => denyReason(p) !== null

const versionOf = name => name.match(/^(\d+)\.(\d+)\.(\d+)$/)?.slice(1).map(Number) ?? null
const cmpVersion = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]

function versionDirs(paths, parent, prefix) {
  const seen = new Map()
  for (const p of paths) {
    if (!p.startsWith(parent + prefix)) continue
    const dir = p.slice(parent.length).split('/')[0]
    const v = versionOf(dir.slice(prefix.length))
    if (v) seen.set(dir, v)
  }
  return [...seen].sort((a, b) => cmpVersion(a[1], b[1])).map(([dir]) => dir)
}

function isSitePage(rel) {
  if (!rel.endsWith('.md') || rel === 'README.md') return false
  return !rel.includes('/') || SITE_PAGE_DIRS.some(d => rel.startsWith(d) && !rel.slice(d.length).includes('/'))
}

// 傳回 { kind: 'allow', dest } ／ { kind: 'deny', reason } ／ { kind: 'unlisted' }
function makeClassifier(latestPro, latestBasic, oldPro, oldBasic, latestProofread, oldProofread) {
  return p => {
    const reason = denyReason(p)
    if (reason) return { kind: 'deny', reason }
    if (p.startsWith(PRO_PARENT)) {
      const rel = p.slice(PRO_PARENT.length)
      const top = rel.split('/')[0]
      if (latestPro && top === latestPro) return { kind: 'allow', dest: 'pro/' + rel }
      if (oldPro.includes(top)) return { kind: 'deny', reason: '舊版目錄（只帶最新版，重點寫在更版紀錄）' }
      if (rel.startsWith('tests/')) return { kind: 'allow', dest: 'pro/' + rel }
      if (/^tools\/[^/]+\.py$/.test(rel)) return { kind: 'allow', dest: 'pro/' + rel }
      return { kind: 'unlisted' }
    }
    if (p.startsWith(BASIC_PARENT)) {
      const rel = p.slice(BASIC_PARENT.length)
      const top = rel.split('/')[0]
      if (latestBasic && top === latestBasic) return { kind: 'allow', dest: 'basic/' + rel }
      if (oldBasic.includes(top)) return { kind: 'deny', reason: '舊版目錄（只帶最新版）' }
      return { kind: 'unlisted' }
    }
    if (p.startsWith(PROOFREAD_PARENT)) {
      const rel = p.slice(PROOFREAD_PARENT.length)
      const top = rel.split('/')[0]
      if (latestProofread && top === latestProofread) return { kind: 'allow', dest: 'proofread/' + rel }
      if (oldProofread.includes(top)) return { kind: 'deny', reason: '舊版目錄（只帶最新版）' }
      if (rel.startsWith('tests/') || rel.startsWith('tools/') || rel === '.gitattributes') return { kind: 'allow', dest: 'proofread/' + rel }
      return { kind: 'unlisted' }
    }
    if (/^docs\/spec\/[^/]+\.md$/.test(p)) return { kind: 'allow', dest: p }
    if (p.startsWith('site/repo-root/')) return { kind: 'allow', dest: p.slice('site/repo-root/'.length) }
    if (p.startsWith('site/')) {
      const rel = p.slice('site/'.length)
      if (SITE_ALLOW_FILES.includes(rel) || SITE_ALLOW_DIRS.some(d => rel.startsWith(d)) || isSitePage(rel)) return { kind: 'allow', dest: p }
    }
    return { kind: 'unlisted' }
  }
}

// ---------- 輸出目錄 ----------

function isInside(child, parent) {
  const rel = path.relative(parent, child)
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

function prepareOut(out) {
  const repoRoot = git(['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim()
  if (isInside(out, path.resolve(repoRoot))) fail('--out 不得在本 repo 內；請用 repo 外的暫存目錄')
  if (!fs.existsSync(out)) {
    fs.mkdirSync(out, { recursive: true })
    return 'new'
  }
  const entries = fs.readdirSync(out)
  if (!entries.length) return 'empty'
  if (!entries.includes('.git')) fail('--out 已存在且不是空目錄，也不是 git clone；不覆寫')
  // 全域 core.autocrlf=true 時，之後在 clone 裡 git add 會出現 LF→CRLF 警告；匯出檔照來源原樣寫入，所以固定在 clone 自己的設定關掉
  execFileSync('git', ['-C', out, 'config', 'core.autocrlf', 'false'])
  console.log('--out 是既有 clone：已設定 git -C <out> config core.autocrlf false')
  for (const name of entries) {
    if (name !== '.git') fs.rmSync(path.join(out, name), { recursive: true, force: true })
  }
  return 'clone'
}

function walkFiles(dir, rel = '') {
  const out = []
  for (const entry of fs.readdirSync(path.join(dir, rel), { withFileTypes: true })) {
    if (entry.name === '.git' && !rel) continue
    const p = rel + entry.name
    if (entry.isDirectory()) out.push(...walkFiles(dir, p + '/'))
    else out.push(p)
  }
  return out
}

const kb = n => `${(n / 1024).toFixed(1)} KB`
const area = dest => (dest.includes('/') ? (/^(pro|basic|proofread)\//.test(dest) ? dest.split('/').slice(0, 2).join('/') : dest.split('/')[0]) : '（根目錄）')

function runScan(args, targets, label) {
  const scan = spawnSync(
    process.execPath,
    [path.join(SITE, 'scripts', 'deid-scan.mjs'), '--terms', path.resolve(args.terms), '--allow', path.resolve(args.allow), '--internal-ids', ...targets],
    { stdio: 'inherit' }
  )
  if (scan.status !== 0) fail(`${label}沒有通過（exit ${scan.status}）；不要推送，修正來源後重新匯出`)
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  const source = args.worktree ? sourceFromWorktree() : sourceFromRef(args.ref)

  const proDirs = versionDirs(source.paths, PRO_PARENT, PRO_PREFIX)
  const basicDirs = versionDirs(source.paths, BASIC_PARENT, BASIC_PREFIX)
  const latestPro = proDirs.at(-1) ?? null
  const latestBasic = basicDirs.at(-1) ?? null
  const proofreadDirs = versionDirs(source.paths, PROOFREAD_PARENT, PROOFREAD_PREFIX)
  const latestProofread = proofreadDirs.at(-1) ?? null
  const classify = makeClassifier(latestPro, latestBasic, proDirs.slice(0, -1), basicDirs.slice(0, -1), latestProofread, proofreadDirs.slice(0, -1))

  const release = JSON.parse(source.read('site/.vitepress/mm-release.json').toString('utf8'))
  const problems = []
  if (latestPro !== PRO_PREFIX + release.proVersion) problems.push(`Pro 最新版目錄是 ${latestPro ?? '（沒有）'}，mm-release.json 是 ${release.proVersion}（S1-a）`)
  if (latestBasic !== BASIC_PREFIX + release.basicVersion) problems.push(`基本版最新版目錄是 ${latestBasic ?? '（沒有）'}，mm-release.json 是 ${release.basicVersion}（S1-c）`)
  if (latestProofread !== PROOFREAD_PREFIX + release.proofreadVersion) problems.push(`會議記錄校稿最新版目錄是 ${latestProofread ?? '（沒有）'}，mm-release.json 是 ${release.proofreadVersion ?? '（沒有）'}`)

  const groups = { allow: [], deny: [], unlisted: [] }
  for (const p of source.paths) {
    const c = classify(p)
    groups[c.kind].push({ p, ...c })
  }
  for (const g of Object.values(groups)) g.sort((a, b) => (a.dest ?? a.p).localeCompare(b.dest ?? b.p))

  const dests = new Set(groups.allow.map(f => f.dest))
  const missing = EXPECTED.map(([d, owner]) => [d.replace('{PRO}', release.proVersion).replace('{BASIC}', release.basicVersion).replace('{PROOF}', release.proofreadVersion), owner]).filter(([d]) => !dests.has(d))
  for (const [d, owner] of missing) problems.push(`缺 ${d}（預期路徑；${owner}）`)

  console.log(`來源：${source.label}；來源根目錄 = site/ 的上一層`)
  console.log(`Pro 版本目錄：${proDirs.join('、') || '（沒有）'} → 帶 ${latestPro ?? '（沒有）'}`)
  console.log(`基本版版本目錄：${basicDirs.join('、') || '（沒有）'} → 帶 ${latestBasic ?? '（沒有）'}`)
  console.log(`會議記錄校稿版本目錄：${proofreadDirs.join('、') || '（沒有）'} → 帶 ${latestProofread ?? '（沒有）'}`)

  console.log(`\n帶（${groups.allow.length}）：`)
  let total = 0
  const files = groups.allow.map(f => {
    const data = source.read(f.p)
    total += data.length
    console.log(`  ${f.dest}  ${data.length}${f.dest !== f.p ? `  ← ${f.p}` : ''}${source.dirty.has(f.p) ? '  （工作目錄有未 commit 改動，用已 commit 版本）' : ''}`)
    return { dest: f.dest, data }
  })
  const byArea = new Map()
  for (const f of files) {
    const a = area(f.dest)
    const cur = byArea.get(a) ?? { n: 0, size: 0 }
    byArea.set(a, { n: cur.n + 1, size: cur.size + f.data.length })
  }
  console.log('\n各區小計：')
  for (const [a, { n, size }] of [...byArea].sort()) console.log(`  ${a}：${n} 檔，${kb(size)}`)

  // 一律排除的依目錄收合成一行（逐檔列出太長）
  const denySummary = new Map()
  for (const f of groups.deny) {
    const denyDir = DENY.find(([d]) => d.endsWith('/') && f.p.startsWith(d))?.[0]
    const key = f.p.endsWith('/') ? f.p : denyDir ?? (f.reason.startsWith('舊版') ? f.p.split('/').slice(0, 2).join('/') + '/' : f.p)
    const cur = denySummary.get(key) ?? { reason: f.reason, n: 0 }
    denySummary.set(key, { reason: cur.reason, n: cur.n + 1 })
  }
  console.log(`\n不帶，一律排除（${groups.deny.length}）：`)
  for (const [k, { reason, n }] of [...denySummary].sort()) console.log(`  ${k}${n > 1 ? `（${n} 檔）` : ''}：${reason}`)
  console.log(`\n不帶，未列入允許清單（${groups.unlisted.length}）：`)
  for (const f of groups.unlisted) console.log(`  ${f.p}`)
  console.log(`\n合計：${files.length} 個檔案，${total} bytes（${kb(total)}）`)

  if (problems.length) {
    console.log(`\n缺項與不一致（${problems.length}）：`)
    for (const m of problems) console.log(`  ⚠ ${m}`)
  } else console.log('\n缺項與不一致：無')

  if (args.dryRun) {
    console.log('\n--dry-run：沒有寫檔，也沒有跑去識別掃描')
    return
  }
  if (problems.length) fail(`有 ${problems.length} 個缺項或版號不一致（見上）；補齊後重新匯出`)

  const out = path.resolve(args.out)
  const mode = prepareOut(out)
  for (const { dest, data } of files) {
    const target = path.join(out, ...dest.split('/'))
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, data)
  }

  // 寫完再核一次：staging 的檔案清單必須剛好等於「帶」的清單
  const written = walkFiles(out).sort()
  const extra = written.filter(p => !dests.has(p))
  if (extra.length || written.length !== files.length) {
    fail(`staging 的檔案清單與允許清單不符：多出 ${extra.join('、') || '（無）'}；寫入 ${written.length}，應為 ${files.length}`)
  }
  const size = written.reduce((n, p) => n + fs.statSync(path.join(out, ...p.split('/'))).size, 0)
  console.log(`\nstaging：${mode === 'clone' ? '既有 clone，已換成這次匯出的內容' : '新目錄'}`)
  console.log(`寫入 ${written.length} 個檔案，${size} bytes（${kb(size)}）`)

  console.log('\n去識別掃描（含內部編號；zip 解開掃）：')
  runScan(args, fs.readdirSync(out).filter(n => n !== '.git').map(n => path.join(out, n)), 'staging 去識別掃描')

  const uncovered = written.filter(p => !isScannable(p) && !BINARY_EXT.has(path.extname(p).toLowerCase()))
  if (uncovered.length) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mm-portal-deid-'))
    try {
      for (const p of uncovered) {
        const target = path.join(tmp, ...p.split('/')) + '.txt'
        fs.mkdirSync(path.dirname(target), { recursive: true })
        fs.copyFileSync(path.join(out, ...p.split('/')), target)
      }
      console.log(`\n補掃 deid-scan 不收的檔案（${uncovered.join('、')}）：`)
      runScan(args, [tmp], '補掃')
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true })
    }
  }
  console.log(`\n完成：${written.length} 個檔案、${kb(size)}、去識別掃描 0${source.sha ? `；來源 commit ${source.sha}` : ''}`)
}

main()

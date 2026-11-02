# 安装

## 给人看

### 前置

| 项 | 要求 |
|---|---|
| DSH | 0.2.1-rc.3 或更新 |
| Python | 3.9+（`scripts/check-python.mjs` 会检查） |
| 密钥 | 至少一个：Zhipu / SiliconFlow / Agnes / SenseNova / Gemini（全部免费） |

### 三选一

**A. GUI（桌面版推荐）**

设置 → 插件 → 安装 → 选本仓库目录 → 重启 DSH。

**B. `dsh plugin`（Web / TUI profile）**

```sh
dsh plugin --profile <profile> add link:<本仓库绝对路径>
```

> 桌面版的 `desktop` profile 由 Electron 独占管理，这条命令会被拒绝，请用 A 或 C。

**C. 手工**

`~/.dsh/profiles/<profile>/package.json` 两处：`dependencies` 加 `"dsh-media-skills": "link:<绝对路径>"`，`dsh.profile.bundles` 加 `"dsh-media-skills"`，然后 `pnpm install --no-frozen-lockfile`，重启。

### 配密钥

密钥**不在仓库里**。按顺序读取：环境变量 → `~/.dsh/secrets/media-tools.env` → `~/.codex/secrets/media-tools.env`（旧路径回退）。

```sh
# ~/.dsh/secrets/media-tools.env   （chmod 600）
GLM_API_KEY=...
SILICONFLOW_API_KEY=...
GEMINI_API_KEY=...   # 可选
```

拿 key 的地方见 [README](README.md#-keys--privacy)。

### 验证

重启后，在新会话里说「生成一张海边的猫」，或「看一下这张截图的文字」。技能出现在技能目录里即安装成功。

### 卸载

```sh
dsh plugin --profile <profile> remove dsh-media-skills
```

---

## 给 agent 执行

你负责配置，**不能重启 DSH**。

```powershell
$dshHome  = Join-Path $env:USERPROFILE '.dsh'
$profile  = 'desktop'
$profDir  = Join-Path $dshHome "profiles\$profile"
$plugDir  = Join-Path $dshHome 'plugins\dsh-media-skills'
"profile dir   : $(Test-Path $profDir)"
"already there : $(Test-Path $plugDir)"
"secrets file  : $(Test-Path (Join-Path $dshHome 'secrets\media-tools.env'))"
```

写权限探测：

```powershell
try { New-Item -ItemType Directory -Force -Path (Join-Path $dshHome 'plugins') | Out-Null; "WRITABLE" }
catch { "BLOCKED: $($_.Exception.Message)" }
```

有权限时：

```powershell
Copy-Item -Recurse -Force '<本仓库绝对路径>' $plugDir
```

改 profile 的 `package.json` 两处（`dependencies` 的 `link:` + `dsh.profile.bundles` 追加），跑 `pnpm install --no-frozen-lockfile`，确认：

```powershell
Test-Path (Join-Path $profDir 'node_modules\dsh-media-skills')
```

**密钥**：不要在对话里索取或回显 key。只检查文件是否存在；不存在时告诉人去配，不要代填。

最后交给人重启。

### 失败分支

| 现象 | 处理 |
|---|---|
| 技能不出现 | `bundles` 没写，或没重启 |
| 技能报缺少 key | 检查三个读取位置，让用户自己配 |
| Python 检查失败 | 装 3.9+，或让用户确认 `python` 在 PATH |
| 生成超时 | 换模型或换服务商，见 SKILL.md |

### 回滚

删两处配置 → 删 `~/.dsh/plugins/dsh-media-skills` → 重启。

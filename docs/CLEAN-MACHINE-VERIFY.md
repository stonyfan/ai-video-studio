# Phase 4 干净机器验证清单

> 用途：在未装 Python / Node 的 Windows 11 机器上验证桌面客户端能完整跑通
> 目的：确认 PyInstaller 打包的 worker、ffmpeg、视频素材解析、登录态、自动更新在真实用户环境下没问题

## 0. 准备测试机

- 一台 Windows 11（最好没装过 Python / Node / FFmpeg；装过 git/VSCode 不影响）
- 网络：能访问后端域名（开发期可用 `http://<开发机内网IP>:8000`）
- U盘 或 网络共享，把安装包拷过去：`D:/ai-video-studio/desktop/release/AI Video Studio Setup 0.4.0.exe`
- 同时拷一份测试素材：`D:/ai-video-studio/samples/dunhuang_mini/`（8 个 .mov，约几百 MB）

## 1. 验证清单（按顺序勾）

### 1.1 安装

- [ ] 双击 `AI Video Studio Setup 0.4.0.exe`，UAC 弹窗点"是"
- [ ] 安装向导出现，默认勾选"安装到当前用户目录"
- [ ] 不勾选"为所有用户安装"（保持 `perMachine: false`）
- [ ] 安装路径改成 `D:\AI Video Studio`（验证中英文混合路径解析）
- [ ] 安装完成，勾选"启动 AI Video Studio"

**预期**：登录页正常出现，无白屏（HashRouter 已修复）

### 1.2 配置后端地址

- [ ] 登录页打开后，找设置入口（一般在右下角齿轮图标 / Settings）
- [ ] 把 Backend URL 改成 `http://<开发机内网IP>:8000/api/v1`（不要写 localhost）
- [ ] 保存设置

### 1.3 登录验证

- [ ] 用 admin 账号登录（密码见 `backend/.env` 的 `ADMIN_PASSWORD`）
- [ ] 登录后跳转到 Dashboard（任务列表，应为空）

**预期**：Dashboard 显示"暂无任务"

### 1.4 创建测试账号（用 user_admin.py）

在开发机上跑：
```bash
python scripts/user_admin.py create tester01 --password test123456 --days 7
```

### 1.5 端到端 Job（核心验证）

测试机上：

- [ ] 退出 admin，用 `tester01 / test123456` 登录
- [ ] 点"新建任务"
- [ ] 第 1 步：把 `samples/dunhuang_mini/` 拷到测试机任意路径（如 `D:\test\`），拖入或浏览选择
- [ ] 第 2 步：选"通用"平台
- [ ] 第 3 步：选"快剪"风格
- [ ] 第 4 步：时长滑到 15 秒
- [ ] 第 5 步：Provider 选 qwen-vl，填入 API Key（问开发同学要），点"开始"

**关键观察点**：

- [ ] 进度页 7 阶段都能往前推进（场景识别 / 字幕 / 切分 / 配音 / 渲染 / 合成 / 完成）
- [ ] 不应出现"worker exe 不存在"错误 → 验证 `<InstallDir>/resources/video-worker/video-worker.exe` 解析正确
- [ ] 不应出现"ffmpeg 未找到"错误 → 验证 ffmpeg 打包路径正确
- [ ] 任务跑完后自动跳结果页，视频可预览
- [ ] 点"打开目录"能定位到 `%APPDATA%/ai-video-studio/jobs/job_xxx/final.mp4`

### 1.6 持久化

- [ ] 完全退出应用（任务栏右键退出，不是关窗口）
- [ ] 重新启动 AI Video Studio
- [ ] **预期**：免登录直接进 Dashboard（session_token 已持久化）
- [ ] Dashboard 上能看到刚才跑的 job（jobsRoot 落盘正常）

### 1.7 自动更新

在开发机上跑（造一个新版本）：
```bash
python scripts/seed_release.py  # 创建 v0.4.1 release（包就是当前 setup.exe 改名）
```

测试机上：

- [ ] 等待 30 秒（启动后初始 check 延迟）
- [ ] **预期**：右下角弹"发现新版本 v0.4.1"通知
- [ ] 点"立即下载"，下载进度走完
- [ ] 下载完成后通知变"新版本已就绪"
- [ ] 点"立即安装并重启"
- [ ] **预期**：应用退出，NSIS 安装程序接管，安装完重新启动

### 1.8 卸载（可选）

- [ ] 系统设置 → 应用 → 卸载 AI Video Studio
- [ ] **预期**：`%APPDATA%/ai-video-studio/` 保留（`deleteAppDataOnUninstall: false`）
  - 即 jobs 历史不丢，下次重装还能看

## 2. 常见问题排查

| 现象 | 可能原因 | 排查 |
|------|---------|------|
| 白屏 | HashRouter 失效（已修）| F12 看 console |
| 卡在"worker 启动中" | `resources/video-worker/` 缺文件 | 检查安装目录 |
| ffmpeg 报错 | PyInstaller 漏 hook | 看 jobs/<id>/logs/stderr.log |
| 登录 401 | backend 没起 / 防火墙 | curl `http://<dev-ip>:8000/api/v1/health` |
| 自动更新不弹 | check 请求被防火墙拦 | dev tools Network 看 `/updates/check` |

## 3. 通过标准

**全部勾选 1.1–1.7** = Phase 4 干净机器验证通过，可以对外发布。

1.8 卸载保留数据是设计预期，不是 bug。

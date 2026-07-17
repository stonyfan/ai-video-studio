/**
 * 路径解析：dev 与 prod（packaged）区分
 *
 * dev: 项目源码目录
 *   - worker: D:/ai-video-studio/dist/video-worker/video-worker.exe
 *   - configs: D:/ai-video-studio/configs/
 *
 * prod: 安装后（NSIS）
 *   - worker: <InstallDir>/resources/video-worker/video-worker.exe
 *   - configs: <InstallDir>/resources/configs/
 */
import { app } from 'electron'
import * as path from 'path'
import * as fs from 'fs'

/** 是否为打包后的生产环境 */
export function isPackaged(): boolean {
  return app.isPackaged
}

/** worker 可执行文件路径 */
export function workerExePath(): string {
  if (isPackaged()) {
    return path.join(process.resourcesPath, 'video-worker', 'video-worker.exe')
  }
  // dev: 项目根目录下的 PyInstaller 产物
  // out/main/main.js 上溯 3 级 = 项目根（ai-video-studio/）
  const projectRoot = path.resolve(__dirname, '..', '..', '..')
  return path.join(projectRoot, 'dist', 'video-worker', 'video-worker.exe')
}

/** configs 目录路径 */
export function configsDir(): string {
  if (isPackaged()) {
    return path.join(process.resourcesPath, 'configs')
  }
  const projectRoot = path.resolve(__dirname, '..', '..', '..')
  return path.join(projectRoot, 'configs')
}

/** 默认 config.yaml 路径 */
export function defaultYamlPath(): string {
  return path.join(configsDir(), 'default.yaml')
}

/** 随客户端分发的默认 prompts.yaml（fallback：用户未拉到 prompt 集时用） */
export function bundledPromptsPath(): string {
  return path.join(configsDir(), 'prompts.yaml')
}

/** 用户数据目录（%APPDATA%/ai-video-studio/）*/
export function userDataDir(): string {
  // app.getPath('userData') = %APPDATA%/<appName>
  return app.getPath('userData')
}

/** 任务工作根目录（%APPDATA%/ai-video-studio/jobs/）*/
export function jobsRoot(): string {
  const p = path.join(userDataDir(), 'jobs')
  fs.mkdirSync(p, { recursive: true })
  return p
}

/** config.json 路径（Electron 独占）*/
export function configJsonPath(): string {
  return path.join(userDataDir(), 'config.json')
}

/** 检查 worker 是否就绪 */
export function workerExists(): boolean {
  return fs.existsSync(workerExePath())
}

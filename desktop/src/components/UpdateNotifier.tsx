/**
 * 更新通知组件
 *
 * 三种状态：
 * - 普通更新（update:available）：右下角 antd Notification（可关闭），"立即下载"按钮
 * - current_deprecated（update:deprecated）：antd Modal 不可关闭，必须下载安装才能继续
 *   文案："当前版本已不可用"
 * - force_upgrade（update:force-upgrade）：antd Modal 不可关闭，"必须更新到 vX.X.X"
 *   即使有更高版本也只指到 target（后端已确定 target）
 *
 * grace 期内（用户下载了但还没装的版本被回滚）：notification 显示 "已下载的 vXXX 仍可安装"
 * 用户可点"稍后提醒"（普通更新专用，force/deprecated 不允许稍后）
 */
import { useEffect, useRef, useState } from 'react'
import { App, Modal, Typography, Tag } from 'antd'
import { CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons'

import { updaterApi, appApi } from '../api/client'

const { Text, Paragraph } = Typography

interface UpdateInfo {
  has_update: boolean
  latest_version: string | null
  download_url: string | null
  sha256: string | null
  release_notes: string | null
  min_supported: string | null
  current_deprecated: boolean
  force_upgrade?: boolean
  grace_hours?: number | null
}

type ModalKind = 'deprecated' | 'force-upgrade' | null

export default function UpdateNotifier() {
  const { notification } = App.useApp()
  const [modalInfo, setModalInfo] = useState<UpdateInfo | null>(null)
  const [modalKind, setModalKind] = useState<ModalKind>(null)
  const [currentVersion, setCurrentVersion] = useState('未知')
  // 防止重复弹通知：用 latest_version 做幂等 key
  const shownKeys = useRef<Set<string>>(new Set())
  // 当前正在下载的版本，避免并发出多个进度通知
  const downloadingVer = useRef<string | null>(null)

  useEffect(() => {
    appApi.getVersion().then(setCurrentVersion).catch(() => {})
  }, [])

  // 启动时拉一次当前 updater 状态（应对 renderer 启动晚于 main 检测到更新的情况）
  useEffect(() => {
    updaterApi.getState().then((s: unknown) => {
      const state = s as { status: string; info?: UpdateInfo }
      if (state.status === 'available' && state.info) {
        if (state.info.force_upgrade) {
          setModalInfo(state.info)
          setModalKind('force-upgrade')
        } else if (state.info.current_deprecated) {
          setModalInfo(state.info)
          setModalKind('deprecated')
        } else {
          showAvailable(state.info)
        }
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    const offAvailable = updaterApi.onAvailable((info) => showAvailable(info))
    const offDeprecated = updaterApi.onDeprecated((info) => {
      setModalInfo(info)
      setModalKind('deprecated')
    })
    const offForceUpgrade = updaterApi.onForceUpgrade((info) => {
      setModalInfo(info)
      setModalKind('force-upgrade')
    })
    const offProgress = updaterApi.onProgress((_p) => {
      // antd notification 没有官方 setState API，简化处理：不实时刷新进度
      // 用户感知 = "下载中..." 一直转，完成后切到"已就绪"
    })
    const offDownloaded = updaterApi.onDownloaded(({ version, inGrace }) => {
      downloadingVer.current = null
      notification.success({
        key: 'update-downloaded',
        message: inGrace ? `已下载的 v${version} 仍可安装` : `新版本 ${version} 已就绪`,
        description: inGrace
          ? '此版本已从服务端下线（被回滚），但你在宽限期内仍可安装'
          : '点击下方按钮立即安装（应用会退出，由安装程序接管）',
        duration: 0,
        btn: (
          <a onClick={() => updaterApi.install()}
             style={{ cursor: 'pointer', color: '#1677ff' }}>
            立即安装并重启
          </a>
        ),
        icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />
      })
    })
    const offFailed = updaterApi.onFailed(({ error }) => {
      notification.error({
        key: 'update-error',
        message: '更新失败',
        description: error,
        duration: 8
      })
    })
    return () => {
      offAvailable()
      offDeprecated()
      offForceUpgrade()
      offProgress()
      offDownloaded()
      offFailed()
    }
  }, [])

  const showAvailable = (info: UpdateInfo) => {
    if (!info.latest_version) return
    if (shownKeys.current.has(info.latest_version)) return
    shownKeys.current.add(info.latest_version)
    notification.info({
      key: `update-${info.latest_version}`,
      message: <>发现新版本 <Tag color="blue">v{info.latest_version}</Tag></>,
      description: info.release_notes || '点击下载安装包',
      duration: 0,
      btn: (
        <>
          <a onClick={() => updaterApi.remindLater()}
             style={{ cursor: 'pointer', color: '#999', paddingRight: 12 }}>
            稍后提醒
          </a>
          <a onClick={() => startDownload(info)}
             style={{ cursor: 'pointer', color: '#1677ff' }}>
            <DownloadOutlined /> 立即下载
          </a>
        </>
      )
    })
  }

  const startDownload = async (info: UpdateInfo) => {
    if (!info.latest_version) return
    notification.destroy(`update-${info.latest_version}`)
    if (downloadingVer.current) return
    downloadingVer.current = info.latest_version
    notification.info({
      key: `update-downloading-${info.latest_version}`,
      message: <>下载中 v{info.latest_version}…</>,
      description: '下载完成后会自动通知你安装',
      duration: 0,
      icon: <DownloadOutlined spin />
    })
    await updaterApi.download()
    notification.destroy(`update-downloading-${info.latest_version}`)
  }

  if (modalInfo && modalKind) {
    const isForce = modalKind === 'force-upgrade'
    return (
      <Modal
        open={true}
        closable={false}
        maskClosable={false}
        keyboard={false}
        title={
          isForce ? (
            <>必须更新到 <Tag color="red">v{modalInfo.latest_version}</Tag></>
          ) : (
            <>当前版本已不可用 <Tag color="red">必须更新</Tag></>
          )
        }
        footer={[
          <a key="download" onClick={() => startDownload(modalInfo)}
             style={{ color: '#1677ff', cursor: 'pointer', paddingRight: 12 }}>
            <DownloadOutlined /> 立即下载
          </a>
        ]}
      >
        <Paragraph>
          {isForce ? (
            <>
              你的版本 <Text code>v{currentVersion}</Text> 必须升级到
              {' '}<Text code>v{modalInfo.latest_version}</Text> 才能继续使用。
            </>
          ) : (
            <>
              你的版本 <Text code>v{currentVersion}</Text> 已低于最低支持版本
              {' '}<Text code>v{modalInfo.min_supported}</Text>，必须更新到
              {' '}<Text code>v{modalInfo.latest_version}</Text> 才能继续使用。
            </>
          )}
        </Paragraph>
        {modalInfo.release_notes && (
          <Paragraph type="secondary">{modalInfo.release_notes}</Paragraph>
        )}
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
          关闭窗口：下载完成后系统会自动提示安装。
        </Paragraph>
      </Modal>
    )
  }
  return null
}

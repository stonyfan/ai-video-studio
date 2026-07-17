/**
 * 设置页 — 模型调用模式 / AI Provider API Key 配置 / Prompt 集 / 账号信息 / 高级设置
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Form, Input, Button, Space, Typography, Descriptions,
  Tag, Alert, App, Divider, Popconfirm, Collapse, Segmented, Select, Skeleton
} from 'antd'
import {
  CheckCircleOutlined, LogoutOutlined,
  ApiOutlined, CloudServerOutlined, SyncOutlined, SafetyCertificateOutlined,
  FileTextOutlined
} from '@ant-design/icons'

import { useAuthStore } from '../store/auth'
import { configApi, authApi, appApi, updaterApi, promptSetApi } from '../api/client'
import type { Provider, PromptSetOption } from '../../electron/types'

const { Title, Text, Paragraph, Link } = Typography

interface ProviderInfo {
  id: Provider
  name: string
  description: string
  keyUrl: string
  defaultModel: string
}

const PROVIDERS: ProviderInfo[] = [
  {
    id: 'qwen-vl',
    name: '阿里 Qwen-VL',
    description: '通义千问视觉模型，国内首选',
    keyUrl: 'https://dashscope.console.aliyun.com',
    defaultModel: 'qwen-vl-plus'
  },
  {
    id: 'doubao',
    name: '字节豆包',
    description: '火山方舟视觉模型（按量付费）',
    keyUrl: 'https://console.volcengine.com/ark',
    defaultModel: 'doubao-1.5-vision-pro'
  },
  {
    id: 'doubao-agent-plan',
    name: '字节豆包 Agent Plan',
    description: '火山方舟订阅套餐（走套餐额度，不扣账户余额）',
    keyUrl: 'https://console.volcengine.com/ark',
    defaultModel: ''
  },
  {
    id: 'glm',
    name: '智谱 GLM-4V',
    description: '智谱 BigModel 视觉模型',
    keyUrl: 'https://open.bigmodel.cn/console/apikey',
    defaultModel: 'glm-4v-plus'
  }
]

export default function Settings() {
  const nav = useNavigate()
  const { user, logout, refreshConfig } = useAuthStore()
  const { message, modal } = App.useApp()
  const [form] = Form.useForm()
  const [version, setVersion] = useState('?')
  const [backendUrl, setBackendUrl] = useState('')
  const [modelMode, setModelMode] = useState<'A' | 'C'>('A')
  const [checking, setChecking] = useState(false)
  const [updateInfo, setUpdateInfo] = useState<{
    has_update: boolean
    latest_version: string | null
    release_notes: string | null
  } | null>(null)
  const [savedKeys, setSavedKeys] = useState<Record<Provider, boolean>>({
    'qwen-vl': false,
    doubao: false,
    'doubao-agent-plan': false,
    glm: false
  })
  const [promptOptions, setPromptOptions] = useState<PromptSetOption[]>([])
  const [promptLoading, setPromptLoading] = useState(false)
  const [promptSwitching, setPromptSwitching] = useState(false)

  const loadConfig = async () => {
    const cfg = await configApi.getAll()
    setBackendUrl(cfg.backend_url)
    setModelMode(cfg.model_mode || 'A')
    setSavedKeys({
      'qwen-vl': !!cfg.provider_keys['qwen-vl']?.key,
      doubao: !!cfg.provider_keys['doubao']?.key,
      'doubao-agent-plan': !!cfg.provider_keys['doubao-agent-plan']?.key,
      glm: !!cfg.provider_keys['glm']?.key
    })
    // 预填表单
    for (const p of PROVIDERS) {
      const existing = cfg.provider_keys[p.id]
      if (existing) {
        form.setFieldValue([p.id, 'key'], existing.key)
        form.setFieldValue([p.id, 'model'], existing.model || '')
      }
    }
  }

  useEffect(() => {
    loadConfig()
    appApi.getVersion().then(setVersion)
    loadPromptOptions()
  }, [])

  const loadPromptOptions = async () => {
    setPromptLoading(true)
    try {
      const opts = await promptSetApi.listOptions()
      setPromptOptions(opts)
    } catch (e) {
      message.error(`加载 prompt 集失败: ${(e as Error).message}`)
    } finally {
      setPromptLoading(false)
    }
  }

  const handlePromptSelect = (id: number) => {
    const target = promptOptions.find(o => o.id === id)
    if (!target) return
    const current = promptOptions.find(o => o.is_current)
    if (current?.id === id) return  // 跟当前一样直接返回

    modal.confirm({
      title: '切换 Prompt 集？',
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Paragraph style={{ marginBottom: 0 }}>
            将从「<Text strong>{current?.name || '默认'}</Text>」
            {' → '}
            切换到「<Text strong>{target.name}</Text>」
          </Paragraph>
          {target.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>{target.description}</Text>
          )}
          <Alert
            type="info"
            showIcon
            message="下次任务生效"
            description="切换后立即拉取新 prompt 模板；正在运行的任务不受影响。"
            style={{ marginTop: 8 }}
          />
        </Space>
      ),
      okText: '切换',
      cancelText: '取消',
      onOk: async () => {
        setPromptSwitching(true)
        try {
          await promptSetApi.select(id)
          message.success(`已切换到「${target.name}」（下次任务生效）`)
          await loadPromptOptions()
        } catch (e) {
          message.error(`切换失败: ${(e as Error).message}`)
        } finally {
          setPromptSwitching(false)
        }
      },
    })
  }

  const saveProvider = async (provider: Provider) => {
    try {
      const key = form.getFieldValue([provider, 'key'])
      const model = form.getFieldValue([provider, 'model'])
      if (!key?.trim()) {
        message.error('请输入 API key')
        return
      }
      await configApi.setProviderKey(provider, key.trim(), model?.trim() || undefined)
      message.success(`${provider} 已保存`)
      await loadConfig()
    } catch (e) {
      message.error(`保存失败: ${(e as Error).message}`)
    }
  }

  const saveBackendUrl = async () => {
    if (!backendUrl.trim()) {
      message.error('后端地址不能为空')
      return
    }
    await configApi.setBackendUrl(backendUrl.trim())
    message.success('后端地址已更新')
    refreshConfig()
  }

  const switchModelMode = async (mode: 'A' | 'C') => {
    try {
      await configApi.setModelMode(mode)
      setModelMode(mode)
      message.success(`已切换到 ${mode === 'A' ? 'A 模式（直连）' : 'C 模式（云端代理）'}`)
    } catch (e) {
      message.error(`切换失败: ${(e as Error).message}`)
    }
  }

  const handleLogout = async () => {
    await logout()
    nav('/login', { replace: true })
  }

  const checkUpdate = async () => {
    setChecking(true)
    try {
      const info = await updaterApi.check()
      if (!info) {
        message.warning('检查失败：后端无响应')
        return
      }
      setUpdateInfo(info)
      if (info.has_update) {
        message.info(`发现新版本 v${info.latest_version}，请在右下角通知中下载`)
      } else {
        message.success('已是最新版本')
      }
    } catch (e) {
      message.error(`检查失败: ${(e as Error).message}`)
    } finally {
      setChecking(false)
    }
  }

  const proxyExample = backendUrl
    ? `${backendUrl.replace(/\/api\/v1\/?$/, '')}/api/v1/vision/{provider}/chat/completions`
    : 'http://localhost:8000/api/v1/vision/{provider}/chat/completions'

  return (
    <Form form={form} component={false}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Card title={<Space><SafetyCertificateOutlined /> 模型调用模式</Space>}>
          <Segmented
            value={modelMode}
            onChange={v => switchModelMode(v as 'A' | 'C')}
            options={[
              { label: 'A 模式 - 直连（自带 key）', value: 'A' },
              { label: 'C 模式 - 云端代理（后端托管 key）', value: 'C' },
            ]}
            block
          />
          {modelMode === 'A' ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message="A 模式：用户自带 API key"
              description="key 保存在 %APPDATA%/ai-video-studio/config.json，仅本机使用，不会上传到服务端。适用于个人开发 / 自部署。"
            />
          ) : (
            <Alert
              type="success"
              showIcon
              style={{ marginTop: 16 }}
              message="C 模式：模型 key 由后端托管"
              description={<>调用走 <Text code>{proxyExample}</Text>，鉴权用当前登录 JWT。无需在本机填 key；admin 在后台 <Text code>Provider Keys</Text> 页面管理。限速由后端统一控制。</>}
            />
          )}
        </Card>

        <Card title={<Space><ApiOutlined /> AI Provider API Key</Space>}>
          {modelMode === 'C' ? (
            <Alert
              type="warning"
              showIcon
              message="C 模式下不需要本机配置 key"
              description="key 由后端管理，下方表单仅供 A 模式使用。如需调整模型名（如 qwen-vl-max），仍可填写并保存。"
              style={{ marginBottom: 16 }}
            />
          ) : (
            <Alert
              type="info"
              showIcon
              message="A 模式：用户自带 API key"
              description="key 保存在 %APPDATA%/ai-video-studio/config.json，仅本机使用，不会上传到服务端。"
              style={{ marginBottom: 16 }}
            />
          )}
          {PROVIDERS.map(p => (
            <div key={p.id}>
              <Space style={{ marginBottom: 8 }}>
                <Title level={5} style={{ margin: 0 }}>{p.name}</Title>
                {savedKeys[p.id]
                  ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                  : <Tag color="default">未配置</Tag>}
                <Link href={p.keyUrl} target="_blank">获取 key</Link>
              </Space>
              <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                {p.description} · 默认模型 <Text code>{p.defaultModel}</Text>
              </Paragraph>
              <Form.Item noStyle>
                <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                  <Form.Item name={[p.id, 'key']} noStyle>
                    <Input.Password
                      placeholder="API key（输入不回显）"
                      style={{ flex: 2 }}
                      disabled={modelMode === 'C'}
                    />
                  </Form.Item>
                  <Form.Item name={[p.id, 'model']} noStyle>
                    <Input placeholder={`模型名（默认 ${p.defaultModel}）`} style={{ flex: 1 }} />
                  </Form.Item>
                  <Button
                    type="primary"
                    onClick={() => saveProvider(p.id)}
                    disabled={modelMode === 'C'}
                  >保存</Button>
                </Space.Compact>
              </Form.Item>
              <Divider style={{ margin: '16px 0' }} />
            </div>
          ))}
        </Card>

        <Card title={<Space><FileTextOutlined /> Prompt 集</Space>}>
          <Paragraph type="secondary" style={{ marginBottom: 16 }}>
            当前使用的 prompt 集，影响 AI 视频生成的指令模板。切换后下次任务生效。
          </Paragraph>
          {promptLoading ? (
            <Skeleton active paragraph={{ rows: 2 }} />
          ) : promptOptions.length === 0 ? (
            <Alert
              type="warning"
              showIcon
              message="无可选 prompt 集"
              description="请联系管理员分配可用 prompt 集。"
            />
          ) : (
            <>
              <Form.Item label="当前使用的 prompt 集">
                <Select
                  value={promptOptions.find(o => o.is_current)?.id}
                  loading={promptSwitching}
                  onChange={handlePromptSelect}
                  style={{ maxWidth: 480 }}
                  options={promptOptions.map(o => ({
                    value: o.id,
                    label: (
                      <Space>
                        <span>{o.name}</span>
                        <Text type="secondary">v{o.version}</Text>
                        {o.is_default && <Tag color="blue">默认</Tag>}
                        {o.is_current && <Tag color="green">当前</Tag>}
                      </Space>
                    ),
                  }))}
                />
              </Form.Item>
              {(() => {
                const cur = promptOptions.find(o => o.is_current)
                return cur?.description ? (
                  <Text type="secondary">{cur.description}</Text>
                ) : null
              })()}
            </>
          )}
        </Card>

        <Card title="账号信息">
          <Descriptions column={1}>
            <Descriptions.Item label="用户名">{user?.username || '-'}</Descriptions.Item>
            <Descriptions.Item label="角色">
              {user?.role === 'admin' ? <Tag color="gold">admin</Tag> : <Tag>user</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="授权到期">
              {user?.license_expires_at || '永久'}
            </Descriptions.Item>
            <Descriptions.Item label="客户端版本">v{version}</Descriptions.Item>
            <Descriptions.Item label="更新状态">
              {updateInfo?.has_update
                ? <Tag color="blue">有新版本 v{updateInfo.latest_version}</Tag>
                : updateInfo
                  ? <Tag color="green" icon={<CheckCircleOutlined />}>已是最新</Tag>
                  : <Tag color="default">未检查</Tag>}
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 8 }}>
            <Button icon={<SyncOutlined />} loading={checking} onClick={checkUpdate}>
              检查更新
            </Button>
            <Popconfirm
              title="确认退出登录？"
              okText="退出"
              cancelText="取消"
              onConfirm={handleLogout}
            >
              <Button danger icon={<LogoutOutlined />}>退出登录</Button>
            </Popconfirm>
          </Space>
        </Card>

        <Card>
          <Collapse
            defaultActiveKey={[]}
            items={[{
              key: 'advanced',
              label: <Space><CloudServerOutlined /> 高级设置</Space>,
              children: (
                <>
                  <Paragraph type="secondary">
                    后端服务地址。默认本地开发用 <Text code>http://localhost:8000/api/v1</Text>，
                    生产请改成实际部署地址。改错会导致登录/任务全部失败。
                  </Paragraph>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      value={backendUrl}
                      onChange={e => setBackendUrl(e.target.value)}
                      placeholder="http://localhost:8000/api/v1"
                    />
                    <Button type="primary" onClick={saveBackendUrl}>保存</Button>
                  </Space.Compact>
                </>
              )
            }]}
          />
        </Card>
      </Space>
    </Form>
  )
}

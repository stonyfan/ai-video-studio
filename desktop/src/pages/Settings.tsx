/**
 * 设置页 — API key 配置 / 后端 URL / 用户信息 / 登出
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Form, Input, Button, Space, Typography, Descriptions,
  Tag, Alert, message, Divider, Popconfirm
} from 'antd'
import {
  CheckCircleOutlined, LogoutOutlined, ReloadOutlined,
  ApiOutlined, CloudServerOutlined
} from '@ant-design/icons'

import { useAuthStore } from '../store/auth'
import { configApi, authApi, appApi } from '../api/client'
import type { Provider } from '../../electron/types'

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
    description: '火山方舟视觉模型',
    keyUrl: 'https://console.volcengine.com/ark',
    defaultModel: 'doubao-1.5-vision-pro'
  }
]

export default function Settings() {
  const nav = useNavigate()
  const { user, logout, refreshConfig } = useAuthStore()
  const [form] = Form.useForm()
  const [version, setVersion] = useState('?')
  const [backendUrl, setBackendUrl] = useState('')
  const [savedKeys, setSavedKeys] = useState<Record<Provider, boolean>>({
    'qwen-vl': false,
    doubao: false
  })

  const loadConfig = async () => {
    const cfg = await configApi.getAll()
    setBackendUrl(cfg.backend_url)
    setSavedKeys({
      'qwen-vl': !!cfg.provider_keys['qwen-vl']?.key,
      doubao: !!cfg.provider_keys['doubao']?.key
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
  }, [])

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

  const handleLogout = async () => {
    await logout()
    nav('/login', { replace: true })
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Card title={<Space><CloudServerOutlined /> 后端服务</Space>} size="small">
        <Paragraph type="secondary">
          后端服务地址。默认本地开发用 <Text code>http://localhost:8000/api/v1</Text>，
          生产请改成实际部署地址。
        </Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={backendUrl}
            onChange={e => setBackendUrl(e.target.value)}
            placeholder="http://localhost:8000/api/v1"
          />
          <Button type="primary" onClick={saveBackendUrl}>保存</Button>
        </Space.Compact>
      </Card>

      <Card title={<Space><ApiOutlined /> AI Provider API Key</Space>}>
        <Alert
          type="info"
          showIcon
          message="A 模式：用户自带 API key"
          description="key 保存在 %APPDATA%/ai-video-studio/config.json，仅本机使用，不会上传到服务端。"
          style={{ marginBottom: 16 }}
        />
        {PROVIDERS.map(p => (
          <div key={p.id}>
            <Space style={{ marginBottom: 8 }}>
              <Title level={5} style={{ margin: 0 }}>{p.name}</Title>
              {savedKeys[p.id]
                ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                : <Tag color="default">未配置</Tag>}
              <Link href={p.keyUrl} target="_blank">获取 key</Link>
            </Space>
            <Form.Item noStyle>
              <Space.Compact style={{ width: '100%' }}>
                <Form.Item name={[p.id, 'key']} noStyle>
                  <Input.Password placeholder="API key（输入不回显）" style={{ flex: 2 }} />
                </Form.Item>
                <Form.Item name={[p.id, 'model']} noStyle>
                  <Input placeholder={`模型名（默认 ${p.defaultModel}）`} style={{ flex: 1 }} />
                </Form.Item>
                <Button type="primary" onClick={() => saveProvider(p.id)}>保存</Button>
              </Space.Compact>
            </Form.Item>
            <Divider style={{ margin: '16px 0' }} />
          </div>
        ))}
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
        </Descriptions>
        <Popconfirm
          title="确认退出登录？"
          okText="退出"
          cancelText="取消"
          onConfirm={handleLogout}
        >
          <Button danger icon={<LogoutOutlined />}>退出登录</Button>
        </Popconfirm>
      </Card>
    </Space>
  )
}

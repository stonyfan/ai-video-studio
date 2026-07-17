import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, Switch,
  Popconfirm, App, Card, Typography,
} from 'antd'
import { PlusOutlined, ApiOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import {
  providerKeysApi,
  type ProviderKey, type ProviderName,
  type ProviderKeyCreatePayload, type ProviderKeyUpdatePayload,
} from '../api/providerKeys'

const { Text } = Typography

const PROVIDER_OPTIONS: { value: ProviderName; label: string; color: string }[] = [
  { value: 'qwen-vl', label: 'Qwen-VL（阿里）', color: 'blue' },
  { value: 'glm', label: 'GLM（智谱）', color: 'green' },
  { value: 'doubao', label: 'Doubao（字节）', color: 'orange' },
]

const PROVIDER_COLOR: Record<ProviderName, string> = {
  'qwen-vl': 'blue',
  'glm': 'green',
  'doubao': 'orange',
}

interface CreateForm {
  provider: ProviderName
  name: string
  api_key: string
  base_url?: string
  is_active: boolean
}

interface EditForm {
  name: string
  base_url?: string
  is_active: boolean
}

export default function Providers() {
  const { message } = App.useApp()
  const [data, setData] = useState<ProviderKey[]>([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ProviderKey | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [createForm] = Form.useForm<CreateForm>()
  const [editForm] = Form.useForm<EditForm>()

  const refresh = async () => {
    setLoading(true)
    try {
      const list = await providerKeysApi.list()
      setData(list)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const onCreate = async (values: CreateForm) => {
    const payload: ProviderKeyCreatePayload = {
      provider: values.provider,
      name: values.name,
      api_key: values.api_key,
      base_url: values.base_url || undefined,
      is_active: values.is_active,
    }
    try {
      await providerKeysApi.create(payload)
      message.success(`已添加 ${values.provider} key`)
      setCreateOpen(false)
      createForm.resetFields()
      refresh()
    } catch (e) {
      message.error(`添加失败: ${(e as Error).message}`)
    }
  }

  const onEdit = async (values: EditForm) => {
    if (!editTarget) return
    const payload: ProviderKeyUpdatePayload = {
      name: values.name,
      base_url: values.base_url || undefined,
      is_active: values.is_active,
    }
    try {
      await providerKeysApi.update(editTarget.id, payload)
      message.success('已更新')
      setEditTarget(null)
      refresh()
    } catch (e) {
      message.error(`更新失败: ${(e as Error).message}`)
    }
  }

  const onToggleActive = async (k: ProviderKey, checked: boolean) => {
    try {
      await providerKeysApi.update(k.id, { is_active: checked })
      message.success(`${k.provider} ${k.name} 已${checked ? '启用' : '停用'}`)
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const onTest = async (k: ProviderKey) => {
    setTestingId(k.id)
    try {
      const result = await providerKeysApi.test(k.id)
      if (result.ok) {
        message.success(`${k.name}: ${result.message}（${result.latency_ms}ms）`)
      } else {
        message.warning(`${k.name}: ${result.message}`)
      }
    } catch (e) {
      message.error(`测试失败: ${(e as Error).message}`)
    } finally {
      setTestingId(null)
    }
  }

  const onDelete = async (k: ProviderKey) => {
    try {
      await providerKeysApi.delete(k.id)
      message.success(`已删除 ${k.name}`)
      refresh()
    } catch (e) {
      message.error(`删除失败: ${(e as Error).message}`)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: 'Provider', dataIndex: 'provider', width: 140,
      render: (p: ProviderName) => {
        const opt = PROVIDER_OPTIONS.find(o => o.value === p)
        return <Tag color={PROVIDER_COLOR[p]}>{opt?.label || p}</Tag>
      },
    },
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: 'API Key', dataIndex: 'api_key_masked', width: 180,
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: 'Base URL', dataIndex: 'base_url',
      render: (v: string | null) =>
        v ? <Text code copyable style={{ fontSize: 12 }}>{v}</Text>
           : <Text type="secondary">默认</Text>,
    },
    {
      title: '启用', dataIndex: 'is_active', width: 70,
      render: (active: boolean, k: ProviderKey) =>
        <Switch checked={active} size="small" onChange={(c) => onToggleActive(k, c)} />,
    },
    {
      title: '最近使用', dataIndex: 'last_used_at', width: 150,
      render: (v: string | null) => v ? dayjs(v).format('MM-DD HH:mm') : <Text type="secondary">-</Text>,
    },
    {
      title: '操作', width: 220,
      render: (_: unknown, k: ProviderKey) => (
        <Space size="small">
          <Button size="small" icon={<ApiOutlined />}
            loading={testingId === k.id}
            onClick={() => onTest(k)}>测试</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditTarget(k)
            editForm.setFieldsValue({
              name: k.name,
              base_url: k.base_url || '',
              is_active: k.is_active,
            })
          }}>编辑</Button>
          <Popconfirm
            title={`删除 ${k.name}?`}
            description="此操作不可恢复"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(k)}
          >
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>Provider Keys</Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          createForm.resetFields()
          createForm.setFieldsValue({ provider: 'qwen-vl', is_active: true })
          setCreateOpen(true)
        }}>添加 Key</Button>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Text type="secondary">
          Key 加密入库（Fernet，派生自后端 JWT_SECRET）；明文不再返回，仅显示 mask。
          切换 <code>JWT_SECRET</code> 后所有 key 需重新录入。
        </Text>
      </Card>

      <Card>
        <Table
          rowKey="id"
          columns={columns as any}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          size="middle"
        />
      </Card>

      <Modal
        title="添加 Provider Key"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={createForm} layout="vertical" onFinish={onCreate}
          initialValues={{ provider: 'qwen-vl', is_active: true }}>
          <Form.Item name="provider" label="Provider"
            rules={[{ required: true, message: '请选择 provider' }]}>
            <Select options={PROVIDER_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
          </Form.Item>
          <Form.Item name="name" label="名称"
            rules={[
              { required: true, message: '请输入名称' },
              { max: 64 },
            ]}
            extra="便于识别，如 'Qwen-VL 主号'"
          >
            <Input placeholder="Qwen-VL 主号" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key"
            rules={[
              { required: true, message: '请输入 API Key' },
              { max: 512 },
            ]}
            extra="明文存入数据库前会加密"
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL（可选）"
            rules={[{ max: 255 }]}
            extra="留空走 provider 默认 URL（Qwen-VL: dashscope / GLM: bigmodel / Doubao: ark）">
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑 - ${editTarget?.name || ''}`}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit}>
          <Form.Item name="name" label="名称"
            rules={[{ required: true, message: '请输入名称' }, { max: 64 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ max: 255 }]}>
            <Input placeholder="留空走默认" />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

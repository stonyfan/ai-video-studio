import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, DatePicker, Switch,
  Popconfirm, App, Card, Typography,
} from 'antd'
import {
  PlusOutlined, KeyOutlined, ClockCircleOutlined, EditOutlined, FileTextOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'

import { usersApi, type UserListResponse, type UserCreatePayload } from '../api/users'
import { promptSetsApi, type PromptSetSummary } from '../api/promptSets'

const { Text } = Typography

interface CreateForm {
  username: string
  password: string
  role: 'user' | 'admin'
  licenseMode: 'permanent' | 'days'
  licenseDays?: number
  licenseDate?: Dayjs
  phone?: string
  email?: string
  display_name?: string
}

interface EditForm {
  display_name?: string
  phone?: string
  email?: string
}

interface ExtForm {
  mode: 'permanent' | 'days'
  days?: number
  date?: Dayjs
}

interface ResetForm {
  newPassword: string
}

interface PromptAssignForm {
  prompt_set_option_ids: number[]
}

export default function Users() {
  const { message } = App.useApp()
  const [data, setData] = useState<UserListResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<UserListResponse | null>(null)
  const [extTarget, setExtTarget] = useState<UserListResponse | null>(null)
  const [resetTarget, setResetTarget] = useState<UserListResponse | null>(null)
  const [promptTarget, setPromptTarget] = useState<UserListResponse | null>(null)
  const [promptSets, setPromptSets] = useState<PromptSetSummary[]>([])
  const [createForm] = Form.useForm<CreateForm>()
  const [editForm] = Form.useForm<EditForm>()
  const [extForm] = Form.useForm<ExtForm>()
  const [resetForm] = Form.useForm<ResetForm>()
  const [promptForm] = Form.useForm<PromptAssignForm>()

  const refresh = async () => {
    setLoading(true)
    try {
      const [list, sets] = await Promise.all([
        usersApi.list(),
        promptSetsApi.list(),
      ])
      setData(list)
      setPromptSets(sets)
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
    let license_expires_at: string | null = null
    if (values.licenseMode === 'days') {
      const days = values.licenseDays || 30
      license_expires_at = dayjs().add(days, 'day').toISOString()
    } else if (values.licenseDate) {
      license_expires_at = values.licenseDate.toISOString()
    }
    const payload: UserCreatePayload = {
      username: values.username,
      password: values.password,
      role: values.role,
      license_expires_at,
      phone: values.phone?.trim() || undefined,
      email: values.email?.trim() || undefined,
      display_name: values.display_name?.trim() || undefined,
    }
    try {
      await usersApi.create(payload)
      message.success(`已创建 ${values.username}`)
      setCreateOpen(false)
      createForm.resetFields()
      refresh()
    } catch (e) {
      message.error(`创建失败: ${(e as Error).message}`)
    }
  }

  const onEdit = async (values: EditForm) => {
    if (!editTarget) return
    try {
      await usersApi.update(editTarget.id, {
        display_name: values.display_name ?? '',
        phone: values.phone ?? '',
        email: values.email ?? '',
      })
      message.success(`已更新 ${editTarget.username} 的资料`)
      setEditTarget(null)
      refresh()
    } catch (e) {
      message.error(`更新失败: ${(e as Error).message}`)
    }
  }

  const onToggleActive = async (user: UserListResponse) => {
    try {
      await usersApi.update(user.id, { is_active: !user.is_active })
      message.success(`${user.is_active ? '已禁用' : '已启用'} ${user.username}`)
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const onExtend = async (values: ExtForm) => {
    if (!extTarget) return
    let license_expires_at: string | null
    if (values.mode === 'permanent') {
      license_expires_at = null
    } else if (values.days) {
      const base = extTarget.license_expires_at
        ? dayjs(extTarget.license_expires_at)
        : dayjs()
      license_expires_at = base.add(values.days, 'day').toISOString()
    } else {
      message.error('请填写天数')
      return
    }
    try {
      await usersApi.update(extTarget.id, { license_expires_at })
      message.success(`已更新 ${extTarget.username} 的授权`)
      setExtTarget(null)
      extForm.resetFields()
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const onResetPassword = async (values: ResetForm) => {
    if (!resetTarget) return
    try {
      await usersApi.resetPassword(resetTarget.id, values.newPassword)
      message.success(`已重置 ${resetTarget.username} 的密码`)
      setResetTarget(null)
      resetForm.resetFields()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const onDelete = async (user: UserListResponse) => {
    try {
      await usersApi.delete(user.id)
      message.success(`已删除 ${user.username}`)
      refresh()
    } catch (e) {
      message.error(`删除失败: ${(e as Error).message}`)
    }
  }

  const onAssignPrompt = async (values: PromptAssignForm) => {
    if (!promptTarget) return
    try {
      await usersApi.update(promptTarget.id, {
        prompt_set_option_ids: values.prompt_set_option_ids ?? [],
      })
      const n = (values.prompt_set_option_ids ?? []).length
      message.success(`已为 ${promptTarget.username} 分配 ${n} 套 prompt 集`)
      setPromptTarget(null)
      promptForm.resetFields()
      refresh()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(`操作失败: ${typeof detail === 'string' ? detail : (e as Error).message}`)
    }
  }

  const promptSetName = (id: number | null): string => {
    if (id == null) return '默认'
    return promptSets.find(s => s.id === id)?.name || `#${id}`
  }

  const promptPoolSummary = (ids: number[]): string => {
    if (!ids || ids.length === 0) return '默认（系统）'
    if (ids.length <= 2) {
      return ids.map(id => promptSets.find(s => s.id === id)?.name || `#${id}`).join('、')
    }
    const first = promptSets.find(s => s.id === ids[0])?.name || `#${ids[0]}`
    return `${first} +${ids.length - 1}`
  }

  const fmtLicense = (iso: string | null): string => {
    if (!iso) return '永久'
    return dayjs(iso).format('YYYY-MM-DD HH:mm')
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', width: 140 },
    { title: '姓名', dataIndex: 'display_name', width: 120,
      render: (v: string | null) => v || <Text type="secondary">-</Text> },
    { title: '手机号', dataIndex: 'phone', width: 130,
      render: (v: string | null) => v || <Text type="secondary">-</Text> },
    { title: '邮箱', dataIndex: 'email',
      render: (v: string | null) => v ? <Text code style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text> },
    {
      title: '角色', dataIndex: 'role', width: 100,
      render: (role: string) =>
        role === 'admin'
          ? <Tag color="purple">admin</Tag>
          : <Tag>user</Tag>,
    },
    {
      title: '授权到期', dataIndex: 'license_expires_at', width: 180,
      render: (v: string | null) => <Text type={v && dayjs(v).isBefore(dayjs()) ? 'danger' : undefined}>{fmtLicense(v)}</Text>,
    },
    {
      title: '状态', dataIndex: 'is_active', width: 80,
      render: (active: boolean, record: UserListResponse) => (
        <Switch checked={active} size="small" onChange={() => onToggleActive(record)} />
      ),
    },
    {
      title: '当前 Prompt 集', dataIndex: 'prompt_set_id', width: 130,
      render: (id: number | null) => id == null
        ? <Tag>默认</Tag>
        : <Tag color="blue">{promptSetName(id)}</Tag>,
    },
    {
      title: '可选池', dataIndex: 'prompt_set_option_ids', width: 160,
      render: (ids: number[]) => (
        <Text style={{ fontSize: 12 }} type={ids?.length ? undefined : 'secondary'}>
          {promptPoolSummary(ids || [])}
        </Text>
      ),
    },
    {
      title: '操作', width: 380,
      render: (_: unknown, record: UserListResponse) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditTarget(record)
            editForm.setFieldsValue({
              display_name: record.display_name || '',
              phone: record.phone || '',
              email: record.email || '',
            })
          }}>编辑</Button>
          <Button size="small" icon={<KeyOutlined />} onClick={() => {
            setResetTarget(record)
            resetForm.resetFields()
          }}>改密</Button>
          <Button size="small" icon={<ClockCircleOutlined />} onClick={() => {
            setExtTarget(record)
            extForm.resetFields()
          }}>授权</Button>
          <Button size="small" icon={<FileTextOutlined />} onClick={() => {
            setPromptTarget(record)
            promptForm.setFieldsValue({
              prompt_set_option_ids: record.prompt_set_option_ids || [],
            })
          }}>Prompt</Button>
          <Popconfirm
            title={`删除 ${record.username}?`}
            description="此操作不可恢复"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(record)}
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
        <Typography.Title level={4} style={{ margin: 0 }}>用户管理</Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          createForm.resetFields()
          setCreateOpen(true)
        }}>创建账号</Button>
      </div>
      <Card>
        <Table
          rowKey="id"
          columns={columns as any}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          size="middle"
          scroll={{ x: 1100 }}
        />
      </Card>

      <Modal
        title="创建账号"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space>
            <CancelBtn />
            <OkBtn />
          </Space>
        )}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ role: 'user', licenseMode: 'days', licenseDays: 30 }}
          autoComplete="off"
        >
          {/* 隐藏的假字段：消耗浏览器自动填充（Chrome 经常忽略 autoComplete=off） */}
          <input type="text" name="fake_username" style={{ display: 'none' }} autoComplete="username" tabIndex={-1} />
          <input type="password" name="fake_password" style={{ display: 'none' }} autoComplete="current-password" tabIndex={-1} />
          <Form.Item name="username" label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { pattern: /^[a-zA-Z0-9_-]{3,64}$/, message: '3-64 字符，仅字母数字/_-' },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, max: 128, message: '6-128 字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="display_name" label="姓名（选填）"
            rules={[{ max: 64, message: '最多 64 字符' }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="phone" label="手机号（选填）"
            rules={[{ max: 32, message: '最多 32 字符' }]}
          >
            <Input autoComplete="off" placeholder="13800138000" />
          </Form.Item>
          <Form.Item name="email" label="邮箱（选填）"
            rules={[
              { max: 255, message: '最多 255 字符' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input autoComplete="off" placeholder="user@example.com" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select options={[
              { value: 'user', label: '普通用户' },
              { value: 'admin', label: '管理员' },
            ]} />
          </Form.Item>
          <Form.Item name="licenseMode" label="授权">
            <Select options={[
              { value: 'days', label: '有限期（按天数）' },
              { value: 'permanent', label: '永久' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.licenseMode !== b.licenseMode}>
            {({ getFieldValue }) => getFieldValue('licenseMode') === 'days' ? (
              <Form.Item name="licenseDays" label="天数（从今天起）"
                rules={[{ required: true, message: '请填写天数' }]}>
                <Input type="number" min={1} max={3650} addonAfter="天" />
              </Form.Item>
            ) : null}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑资料 - ${editTarget?.username || ''}`}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit} autoComplete="off">
          <Form.Item name="display_name" label="姓名"
            rules={[{ max: 64, message: '最多 64 字符' }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="phone" label="手机号"
            rules={[{ max: 32, message: '最多 32 字符' }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="email" label="邮箱"
            rules={[
              { max: 255, message: '最多 255 字符' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            留空表示清空该字段。用户名/密码/角色/授权请用其他入口修改。
          </Text>
        </Form>
      </Modal>

      <Modal
        title={`调整授权 - ${extTarget?.username || ''}`}
        open={!!extTarget}
        onCancel={() => setExtTarget(null)}
        onOk={() => extForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={extForm} layout="vertical" onFinish={onExtend}
          initialValues={{ mode: 'days', days: 30 }}>
          <Form.Item label="当前授权">
            <Text type="secondary">{extTarget ? fmtLicense(extTarget.license_expires_at) : ''}</Text>
          </Form.Item>
          <Form.Item name="mode" label="新授权">
            <Select options={[
              { value: 'days', label: '延长 N 天' },
              { value: 'permanent', label: '永久' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.mode !== b.mode}>
            {({ getFieldValue }) => getFieldValue('mode') === 'days' ? (
              <Form.Item name="days" label="天数（在当前到期上累加）"
                rules={[{ required: true, message: '请填写' }]}>
                <Input type="number" min={1} max={3650} addonAfter="天" />
              </Form.Item>
            ) : null}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码 - ${resetTarget?.username || ''}`}
        open={!!resetTarget}
        onCancel={() => setResetTarget(null)}
        onOk={() => resetForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={resetForm} layout="vertical" onFinish={onResetPassword} autoComplete="off">
          {/* 假字段吸自动填充 */}
          <input type="text" name="fake_username" style={{ display: 'none' }} autoComplete="username" tabIndex={-1} />
          <input type="password" name="fake_password" style={{ display: 'none' }} autoComplete="current-password" tabIndex={-1} />
          <Form.Item name="newPassword" label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, max: 128, message: '6-128 字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`分配 Prompt 集 - ${promptTarget?.username || ''}`}
        open={!!promptTarget}
        onCancel={() => setPromptTarget(null)}
        onOk={() => promptForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={promptForm} layout="vertical" onFinish={onAssignPrompt}>
          <Form.Item label="当前生效">
            <Text type="secondary">
              {promptTarget ? promptSetName(promptTarget.prompt_set_id) : ''}
              {' '}
              <Text type="secondary" style={{ fontSize: 12 }}>
                (用户在客户端可自由切换下面的可选池)
              </Text>
            </Text>
          </Form.Item>
          <Form.Item
            name="prompt_set_option_ids"
            label="可选 Prompt 集（可多选）"
            tooltip="分配后用户在客户端设置页可自由切换；移除当前生效集时自动 fallback 到默认集"
          >
            <Select
              mode="multiple"
              placeholder="选择 prompt 集（可多选）"
              optionFilterProp="label"
              options={promptSets
                .filter(s => s.is_active)
                .map(s => ({
                  value: s.id,
                  label: `${s.name} (v${s.version})${s.is_default ? ' [默认]' : ''}`,
                }))}
            />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            清空 = 仅使用系统默认集；用户客户端下次启动（或心跳触发）后看到新选项。
          </Text>
        </Form>
      </Modal>
    </div>
  )
}

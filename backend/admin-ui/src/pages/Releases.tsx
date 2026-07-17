import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, Switch, Slider, InputNumber,
  Popconfirm, App, Card, Typography, Progress,
} from 'antd'
import { PlusOutlined, RollbackOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { releasesApi, type Release, type ReleaseCreatePayload, type ReleaseUpdatePayload } from '../api/releases'

const { Text, Paragraph } = Typography

interface CreateForm {
  version: string
  download_url: string
  sha256: string
  min_supported: string
  release_notes?: string
  is_active: boolean
  rollout_percentage: number
  force_upgrade: boolean
  grace_hours: number
}

interface EditForm {
  release_notes?: string
  rollout_percentage: number
  force_upgrade: boolean
  grace_hours: number
  is_active: boolean
}

const VERSION_RE = /^\d+\.\d+\.\d+$/

export default function Releases() {
  const { message } = App.useApp()
  const [data, setData] = useState<Release[]>([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Release | null>(null)
  const [createForm] = Form.useForm<CreateForm>()
  const [editForm] = Form.useForm<EditForm>()

  const refresh = async () => {
    setLoading(true)
    try {
      const list = await releasesApi.list()
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
    const payload: ReleaseCreatePayload = {
      version: values.version,
      download_url: values.download_url,
      sha256: values.sha256.toLowerCase(),
      min_supported: values.min_supported,
      release_notes: values.release_notes || undefined,
      is_active: values.is_active,
      rollout_percentage: values.rollout_percentage,
      force_upgrade: values.force_upgrade,
      grace_hours: values.grace_hours,
    }
    try {
      await releasesApi.create(payload)
      message.success(`已发布 ${values.version}`)
      setCreateOpen(false)
      createForm.resetFields()
      refresh()
    } catch (e) {
      message.error(`发布失败: ${(e as Error).message}`)
    }
  }

  const onEdit = async (values: EditForm) => {
    if (!editTarget) return
    const payload: ReleaseUpdatePayload = {
      release_notes: values.release_notes,
      rollout_percentage: values.rollout_percentage,
      force_upgrade: values.force_upgrade,
      grace_hours: values.grace_hours,
      is_active: values.is_active,
    }
    try {
      await releasesApi.update(editTarget.id, payload)
      message.success(`已更新 ${editTarget.version}`)
      setEditTarget(null)
      refresh()
    } catch (e) {
      message.error(`更新失败: ${(e as Error).message}`)
    }
  }

  const onRollback = async (rel: Release) => {
    try {
      await releasesApi.rollback(rel.id)
      message.success(`已回滚 ${rel.version}`)
      refresh()
    } catch (e) {
      message.error(`回滚失败: ${(e as Error).message}`)
    }
  }

  const onToggleActive = async (rel: Release, checked: boolean) => {
    try {
      await releasesApi.update(rel.id, { is_active: checked })
      message.success(`${rel.version} 已${checked ? '启用' : '停用'}`)
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '版本', dataIndex: 'version', width: 110,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '状态', width: 110,
      render: (_: unknown, r: Release) => {
        if (r.rolled_back_at) return <Tag>已回滚</Tag>
        if (!r.is_active) return <Tag>停用</Tag>
        if (r.force_upgrade) return <Tag color="red">强制升级</Tag>
        return <Tag color="green">活跃</Tag>
      },
    },
    {
      title: '灰度', dataIndex: 'rollout_percentage', width: 160,
      render: (v: number, r: Release) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <Progress percent={v} size="small" showInfo={false}
            strokeColor={r.is_active ? '#1677ff' : '#d9d9d9'} />
          <Text type="secondary" style={{ fontSize: 12 }}>{v}%</Text>
        </Space>
      ),
    },
    {
      title: '下载', dataIndex: 'download_count', width: 70,
      render: (v: number) => <Text>{v ?? 0}</Text>,
    },
    {
      title: '升级成功', width: 110,
      render: (_: unknown, r: Release) => {
        const success = r.upgrade_success_count ?? 0
        const downloads = r.download_count ?? 0
        const rate = downloads > 0 ? Math.round(success / downloads * 100) : 0
        return (
          <Space direction="vertical" size={0}>
            <Text>{success}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>{rate}%</Text>
          </Space>
        )
      },
    },
    {
      title: '强制升级', dataIndex: 'force_upgrade', width: 90,
      render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Text type="secondary">否</Text>,
    },
    {
      title: '宽限期', dataIndex: 'grace_hours', width: 80,
      render: (v: number) => `${v}h`,
    },
    {
      title: '最低兼容', dataIndex: 'min_supported', width: 110,
    },
    {
      title: '启用', dataIndex: 'is_active', width: 70,
      render: (active: boolean, r: Release) => (
        <Switch checked={active} size="small"
          disabled={!!r.rolled_back_at}
          onChange={(checked) => onToggleActive(r, checked)} />
      ),
    },
    {
      title: '发布时间', dataIndex: 'created_at', width: 150,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', width: 180,
      render: (_: unknown, r: Release) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditTarget(r)
            editForm.setFieldsValue({
              release_notes: r.release_notes || '',
              rollout_percentage: r.rollout_percentage,
              force_upgrade: r.force_upgrade,
              grace_hours: r.grace_hours,
              is_active: r.is_active,
            })
          }}>编辑</Button>
          {r.is_active && !r.rolled_back_at && (
            <Popconfirm
              title={`回滚 ${r.version}?`}
              description="is_active=false，已下载客户端不受影响"
              okText="回滚"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => onRollback(r)}
            >
              <Button size="small" danger icon={<RollbackOutlined />}>回滚</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>版本管理</Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          createForm.resetFields()
          createForm.setFieldsValue({
            is_active: true,
            rollout_percentage: 100,
            force_upgrade: false,
            grace_hours: 24,
            min_supported: '0.0.0',
          })
          setCreateOpen(true)
        }}>发布新版本</Button>
      </div>
      <Card>
        <Table
          rowKey="id"
          columns={columns as any}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          size="middle"
          expandable={{
            expandedRowRender: (r: Release) => (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Text type="secondary">下载 URL：</Text>
                <Paragraph copyable style={{ margin: 0 }}>{r.download_url}</Paragraph>
                <Text type="secondary">SHA256：</Text>
                <Text code style={{ display: 'block', wordBreak: 'break-all' }}>{r.sha256}</Text>
                <Text type="secondary">发布说明：</Text>
                <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  {r.release_notes || '（无）'}
                </Paragraph>
                {r.rolled_back_at && (
                  <Text type="secondary">回滚于：{dayjs(r.rolled_back_at).format('YYYY-MM-DD HH:mm')}</Text>
                )}
              </Space>
            ),
          }}
        />
      </Card>

      <Modal
        title="发布新版本"
        open={createOpen}
        width={640}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={createForm} layout="vertical" onFinish={onCreate}
          initialValues={{ is_active: true, rollout_percentage: 100, force_upgrade: false, grace_hours: 24, min_supported: '0.0.0' }}>
          <Form.Item name="version" label="版本号"
            rules={[
              { required: true, message: '请输入版本号' },
              { pattern: VERSION_RE, message: '需符合 x.y.z 格式' },
            ]}
            extra="如 0.7.0"
          >
            <Input placeholder="0.7.0" />
          </Form.Item>
          <Form.Item name="download_url" label="下载 URL"
            rules={[{ required: true, message: '请输入下载 URL' }]}
          >
            <Input placeholder="https://example.com/ai-video-studio-Setup-0.7.0.exe" />
          </Form.Item>
          <Form.Item name="sha256" label="SHA256"
            rules={[
              { required: true, message: '请输入 SHA256' },
              { len: 64, message: '需 64 位' },
            ]}
          >
            <Input placeholder="64 位十六进制" />
          </Form.Item>
          <Form.Item name="min_supported" label="最低兼容版本"
            rules={[
              { required: true, message: '请输入' },
              { pattern: VERSION_RE, message: '需符合 x.y.z 格式' },
            ]}
            extra="低于此版本的客户端将被提示升级"
          >
            <Input />
          </Form.Item>
          <Form.Item name="release_notes" label="发布说明">
            <Input.TextArea rows={4} placeholder="本次更新的内容…" />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="force_upgrade" label="强制升级" valuePropName="checked"
              tooltip="老版本必须升级，否则触发宽限期">
              <Switch />
            </Form.Item>
            <Form.Item name="grace_hours" label="宽限期（小时）">
              <InputNumber min={0} max={720} style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item name="rollout_percentage" label="灰度比例"
            extra="100 表示全量发布">
            <Slider min={0} max={100} marks={{ 0: '0%', 30: '30%', 50: '50%', 100: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑 - ${editTarget?.version || ''}`}
        open={!!editTarget}
        width={560}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit}>
          <Form.Item name="release_notes" label="发布说明">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="rollout_percentage" label="灰度比例">
            <Slider min={0} max={100} marks={{ 0: '0%', 30: '30%', 50: '50%', 100: '100%' }} />
          </Form.Item>
          <Space size="large" style={{ display: 'flex' }}>
            <Form.Item name="force_upgrade" label="强制升级" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="grace_hours" label="宽限期（小时）">
              <InputNumber min={0} max={720} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}

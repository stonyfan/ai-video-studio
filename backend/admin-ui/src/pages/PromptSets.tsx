import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Switch, Select, Popconfirm,
  App, Card, Typography, Tooltip, Upload, type FormInstance,
} from 'antd'
import {
  PlusOutlined, EditOutlined, ReloadOutlined, CopyOutlined, DeleteOutlined,
  FileTextOutlined, UploadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import {
  promptSetsApi, validatePromptYaml,
  type PromptSetSummary, type PromptSetOut,
} from '../api/promptSets'
import YamlCodeMirror from '../components/YamlCodeMirror'

const { Text, Paragraph } = Typography

const DEFAULT_YAML_TEMPLATE = `templates:
  triplet_detect:
    default: |
      {vertical_prompt}
      同一场景 3 个时刻横排（左25%/中50%/右75%）。判断哪帧是最佳瞬间。

      只返回 JSON，无其他文字：
      {"best_frame": "left|mid|right", "cut_duration": <0.5-1.5>, "best_moment": "<5-10字>", "main_objects": ["<obj1>"], "action_type": "<...>", "needs_stabilization": <true|false>}
  scene_analyze:
    default: |
      视频帧。只返回 JSON，无其他文字：
      {"action": "<2-4字>", "objects": ["<obj>"], "shot_type": "<特写|近景|中景|全景>", "visual_quality": <1-10>, "emotional_impact": <1-10>, "best_moment": "<5-10字>"}
  subject_position:
    default: |
      这是横屏视频的中间帧。请按以下格式回复：

      POSITION: <一句话描述主体位置>
      X: <0.0-1.0 浮点数，0.0=最左，1.0=最右>

verticals:
  default: "视频剪辑素材。"
`

interface EditForm {
  name: string
  description?: string
  content_yaml: string
  is_default: boolean
  is_active: boolean
}

export default function PromptSets() {
  const { message, modal } = App.useApp()
  const [data, setData] = useState<PromptSetSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [editTarget, setEditTarget] = useState<PromptSetSummary | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editFull, setEditFull] = useState<PromptSetOut | null>(null)
  const [editForm] = Form.useForm<EditForm>()
  const [createForm] = Form.useForm<EditForm>()
  const [yamlError, setYamlError] = useState<string | null>(null)

  const refresh = async () => {
    setLoading(true)
    try {
      const list = await promptSetsApi.list()
      setData(list)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const onContentChange = (text: string | null | undefined) => {
    setYamlError(validatePromptYaml(text))
  }

  const handleUploadYaml = (form: FormInstance<EditForm>, file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const content = String(reader.result || '')
      form.setFieldValue('content_yaml', content)
      onContentChange(content)
      if (!form.getFieldValue('name')) {
        const baseName = file.name.replace(/\.(ya?ml)$/i, '')
        form.setFieldValue('name', baseName)
      }
      message.success(`已加载 ${file.name}（${content.length} 字符）`)
    }
    reader.onerror = () => message.error('读取文件失败')
    reader.readAsText(file)
    return false
  }

  const onCreate = async (values: EditForm) => {
    const err = validatePromptYaml(values.content_yaml)
    if (err) {
      message.error(`YAML 校验失败：${err}`)
      return
    }
    try {
      await promptSetsApi.create({
        name: values.name,
        description: values.description?.trim() || null,
        content_yaml: values.content_yaml,
        is_default: values.is_default,
        is_active: values.is_active,
      })
      message.success(`已创建 ${values.name}`)
      setCreateOpen(false)
      createForm.resetFields()
      setYamlError(null)
      refresh()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(`创建失败: ${typeof detail === 'string' ? detail : (e as Error).message}`)
    }
  }

  const openEdit = async (row: PromptSetSummary) => {
    try {
      const full = await promptSetsApi.get(row.id)
      setEditFull(full)
      setEditTarget(row)
      setEditOpen(true)
      editForm.setFieldsValue({
        name: full.name,
        description: full.description || '',
        content_yaml: full.content_yaml,
        is_default: full.is_default,
        is_active: full.is_active,
      })
      setYamlError(null)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    }
  }

  const onEdit = async (values: EditForm) => {
    if (!editTarget || !editFull) return
    const err = validatePromptYaml(values.content_yaml)
    if (err) {
      message.error(`YAML 校验失败：${err}`)
      return
    }
    const payload: Record<string, unknown> = {
      name: values.name,
      description: values.description?.trim() || null,
      is_default: values.is_default,
      is_active: values.is_active,
      expected_version: editFull.version,
    }
    if (values.content_yaml !== editFull.content_yaml) {
      payload.content_yaml = values.content_yaml
    }
    try {
      await promptSetsApi.update(editTarget.id, payload)
      message.success(`已更新 ${values.name}`)
      setEditOpen(false)
      setEditTarget(null)
      setEditFull(null)
      setYamlError(null)
      refresh()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(`更新失败: ${typeof detail === 'string' ? detail : (e as Error).message}`)
    }
  }

  const onDuplicate = async (row: PromptSetSummary) => {
    try {
      const created = await promptSetsApi.duplicate(row.id)
      message.success(`已复制为 ${created.name}`)
      refresh()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(`复制失败: ${typeof detail === 'string' ? detail : (e as Error).message}`)
    }
  }

  const onDelete = async (row: PromptSetSummary) => {
    try {
      await promptSetsApi.delete(row.id)
      message.success(`已删除 ${row.name}`)
      refresh()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      message.error(`删除失败: ${typeof detail === 'string' ? detail : (e as Error).message}`)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '名称', dataIndex: 'name', width: 160,
      render: (v: string, r: PromptSetSummary) => (
        <Space>
          <Text strong>{v}</Text>
          {r.is_default && <Tag color="blue">默认</Tag>}
          {!r.is_active && <Tag>停用</Tag>}
        </Space>
      ),
    },
    {
      title: '描述', dataIndex: 'description',
      render: (v: string | null) => v
        ? <Paragraph ellipsis={{ rows: 1 }} style={{ margin: 0, maxWidth: 240 }}>{v}</Paragraph>
        : <Text type="secondary">-</Text>,
    },
    {
      title: '版本', dataIndex: 'version', width: 80,
      render: (v: number) => <Tag color="geekblue">v{v}</Tag>,
    },
    {
      title: '绑定用户', dataIndex: 'bound_user_count', width: 100,
      render: (v: number) => v > 0 ? <Text>{v} 人</Text> : <Text type="secondary">0</Text>,
    },
    {
      title: '更新时间', dataIndex: 'updated_at', width: 160,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss'),
    },
    {
      title: '操作', width: 240,
      render: (_: unknown, r: PromptSetSummary) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Tooltip title="复制为新集（version 重置为 1）">
            <Button size="small" icon={<CopyOutlined />} onClick={() => onDuplicate(r)} />
          </Tooltip>
          {!r.is_default && (
            <Popconfirm
              title={`删除 ${r.name}?`}
              description="软删，可恢复；绑定用户的集无法删除"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => onDelete(r)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const yamlEditor = (form: FormInstance<EditForm>, formName: 'create' | 'edit') => (
    <>
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Upload
          accept=".yaml,.yml"
          showUploadList={false}
          maxCount={1}
          beforeUpload={(file) => handleUploadYaml(form, file)}
        >
          <Button size="small" icon={<UploadOutlined />}>
            从本地 YAML 文件加载
          </Button>
        </Upload>
        <Text type="secondary" style={{ fontSize: 12 }}>
          本地测试好的 prompts.yaml 可一键加载到编辑器
        </Text>
      </div>
      <Form.Item
        name="content_yaml"
        label="Prompt YAML"
        required
        validateStatus={yamlError ? 'error' : undefined}
        help={yamlError || (
          <Text type="secondary" style={{ fontSize: 12 }}>
            必须含 templates.triplet_detect.default；与 video_worker 的 configs/prompts.yaml 同结构
          </Text>
        )}
      >
        <YamlCodeMirror
          onContentChange={(v) => onContentChange(v)}
          placeholder={'templates:\n  triplet_detect:\n    default: |\n      ...'}
          height={formName === 'create' ? '500px' : '450px'}
        />
      </Form.Item>
    </>
  )

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <FileTextOutlined style={{ marginRight: 8 }} />
          Prompt 集
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          createForm.resetFields()
          createForm.setFieldsValue({
            name: '',
            description: '',
            content_yaml: DEFAULT_YAML_TEMPLATE,
            is_default: false,
            is_active: true,
          })
          setYamlError(null)
          setCreateOpen(true)
        }}>新建 Prompt 集</Button>
      </div>

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
        title="新建 Prompt 集"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); setYamlError(null) }}
        onOk={() => createForm.submit()}
        width={900}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ is_default: false, is_active: true, content_yaml: DEFAULT_YAML_TEMPLATE }}
        >
          <Form.Item name="name" label="名称"
            rules={[
              { required: true, message: '请输入名称' },
              { max: 64, message: '最多 64 字符' },
            ]}
          >
            <Input placeholder="如：客户A 专属" />
          </Form.Item>
          <Form.Item name="description" label="描述（选填）"
            rules={[{ max: 255, message: '最多 255 字符' }]}
          >
            <Input placeholder="客户的 prompt 定制说明" />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认集" valuePropName="checked"
            tooltip="设为默认后，原默认集会降级为普通集">
            <Switch />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          {yamlEditor(createForm, 'create')}
        </Form>
      </Modal>

      <Modal
        title={editTarget ? `编辑 ${editTarget.name}` : '编辑'}
        open={editOpen}
        onCancel={() => { setEditOpen(false); setYamlError(null) }}
        onOk={() => editForm.submit()}
        width={900}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前版本 v{editFull?.version}
            </Text>
            <CancelBtn />
            <OkBtn />
          </Space>
        )}
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit}>
          <Form.Item name="name" label="名称"
            rules={[
              { required: true, message: '请输入名称' },
              { max: 64, message: '最多 64 字符' },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述（选填）"
            rules={[{ max: 255, message: '最多 255 字符' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="is_default" label="默认集" valuePropName="checked"
            tooltip="设为默认后，原默认集会降级为普通集">
            <Switch />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          {yamlEditor(editForm, 'edit')}
        </Form>
      </Modal>
    </div>
  )
}

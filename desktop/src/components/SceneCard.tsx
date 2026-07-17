/**
 * SceneCard — 单个候选片段卡片
 *
 * - 内嵌 <video> 真实预览（local-video:// 协议直读本地 MP4）
 * - 左上角 Checkbox 控制勾选
 * - 下方显示元数据：id / action_type / main_objects / 三项分数
 * - 卡片整体可点击切换勾选（除 video 控件区域）
 */
import { Card, Checkbox, Tag, Typography, Tooltip } from 'antd'
import { StarOutlined, StarFilled } from '@ant-design/icons'
import type { Scene } from '../api/curate'

const { Text } = Typography

interface Props {
  scene: Scene
  selected: boolean
  isRepresentative: boolean
  onToggle: (id: string) => void
}

export default function SceneCard({ scene, selected, isRepresentative, onToggle }: Props) {
  const videoUrl = scene.preview_path
    ? `local-video://video?path=${encodeURIComponent(scene.preview_path.replace(/\\/g, '/'))}`
    : ''

  const composite = (
    scene.highlight_score * 0.5 + scene.visual_quality * 0.3 + scene.motion_score * 0.2
  )

  return (
    <Card
      size="small"
      hoverable
      onClick={() => onToggle(scene.id)}
      style={{
        width: '100%',
        borderColor: selected ? '#1677ff' : undefined,
        borderWidth: selected ? 2 : 1,
        background: selected ? '#e6f4ff' : undefined,
      }}
    >
      <div style={{ position: 'relative' }}>
        {videoUrl && scene.preview_ready ? (
          <video
            src={videoUrl}
            controls
            preload="metadata"
            style={{ width: '100%', height: 160, objectFit: 'cover', background: '#000' }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <div style={{
            width: '100%', height: 160, background: '#f0f0f0',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#999', fontSize: 12,
          }}>
            {scene.preview_ready ? '无预览' : '预览生成中…'}
          </div>
        )}
        <div style={{ position: 'absolute', top: 6, left: 6 }}>
          <Checkbox
            checked={selected}
            onClick={(e) => { e.stopPropagation(); onToggle(scene.id) }}
          />
        </div>
        {isRepresentative && (
          <Tooltip title="本 stage 自动选出的代表段（最高 composite 分）">
            <div style={{ position: 'absolute', top: 6, right: 6 }}>
              <Tag color="gold" icon={<StarFilled />} style={{ margin: 0 }}>★</Tag>
            </div>
          </Tooltip>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <Text style={{ fontSize: 12 }} type="secondary">{scene.id}</Text>
        <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Tag color="blue" style={{ fontSize: 11 }}>{scene.action_type || 'unknown'}</Tag>
          <Tag style={{ fontSize: 11 }}>
            <StarOutlined /> {composite.toFixed(1)}
          </Tag>
        </div>
        {scene.main_objects.length > 0 && (
          <Text style={{ fontSize: 11, color: '#666', display: 'block', marginTop: 4 }}>
            {scene.main_objects.slice(0, 3).join(' / ')}
          </Text>
        )}
      </div>
    </Card>
  )
}

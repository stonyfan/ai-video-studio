/**
 * YAML 代码编辑器（CodeMirror 6 封装）
 *
 * 标准 value/onChange 接口，可直接作为 antd Form.Item 的受控子组件。
 * 支持 YAML 语法高亮 + 行号 + 当前行高亮 + 括号匹配。
 */
import { useMemo } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { EditorView } from '@codemirror/view'

interface Props {
  /** antd Form.Item 注入（受控 + 用于 label htmlFor 关联） */
  id?: string
  value?: string
  onChange?: (value: string) => void
  /** 外部 side effect 钩子（如实时 YAML 校验），与 onChange 同时触发 */
  onContentChange?: (value: string) => void
  placeholder?: string
  height?: string
}

export default function YamlCodeMirror({
  id,
  value,
  onChange,
  onContentChange,
  placeholder,
  height = '500px',
}: Props) {
  const extensions = useMemo(() => [yaml(), EditorView.lineWrapping], [])
  return (
    <CodeMirror
      id={id}
      value={value ?? ''}
      onChange={(v) => {
        onChange?.(v)
        onContentChange?.(v)
      }}
      extensions={extensions}
      theme="light"
      height={height}
      placeholder={placeholder}
      style={{
        border: '1px solid #d9d9d9',
        borderRadius: 6,
        fontSize: 13,
        fontFamily: 'Consolas, "Courier New", monospace',
      }}
    />
  )
}

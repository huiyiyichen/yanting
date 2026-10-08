/** Ant Design X Sender 的可访问输入控件与操作按钮。 */
import { PaperClipOutlined } from '@ant-design/icons'
import { Button, Input, type ButtonProps } from 'antd'

/** 稳定的输入组件保留 Sender 的键盘、粘贴与输入法处理。 */
export function makeSenderInput(ariaLabel: string) {
  return function LabelledSenderInput(props: React.ComponentProps<typeof Input.TextArea>) {
    return <Input.TextArea aria-label={ariaLabel} {...props} />
  }
}

/** Sender 的原生发送动作同时维护按钮与键盘提交状态。 */
export function SenderSendButton({
  component: SendButton,
  disabled,
  loading,
}: {
  component: React.ComponentType<ButtonProps>
  disabled?: boolean
  loading?: boolean
}) {
  return (
    <SendButton
      type="primary"
      shape="default"
      icon={null}
      aria-label="发送"
      loading={loading}
      disabled={disabled}
    >
      发送
    </SendButton>
  )
}

/** 回形针按钮由 Attachments 打开文件选择器。 */
export function SenderAttachButton({
  label,
  disabled,
  loading,
  onClick,
}: {
  label: string
  disabled?: boolean
  loading?: boolean
  onClick?: () => void
}) {
  return (
    <Button
      type="text"
      aria-label={label}
      disabled={disabled}
      loading={loading}
      onClick={onClick}
      icon={<PaperClipOutlined style={{ fontSize: 17 }} />}
      style={{ flexShrink: 0, color: 'var(--anker-graphite-soft)' }}
    />
  )
}

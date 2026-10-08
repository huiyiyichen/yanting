import { Attachments } from '@ant-design/x'
import { useCallback, useRef, useState } from 'react'
import type { AttachmentView } from '../api/client'
import { SenderAttachButton } from './SenderParts'

const imageTypes = 'image/jpeg,image/png,image/webp'
type UploadImage = (conversationId: string, file: File) => Promise<AttachmentView>
type ImageDraft = {
  conversationId: string
  name: string
  attachment?: AttachmentView
  uploading: boolean
  error?: string
}

export function useChatImage(conversationId: string | null, uploadImage: UploadImage) {
  const [state, setState] = useState<ImageDraft | null>(null)
  const request = useRef(0)
  const image = state?.conversationId === conversationId ? state : null
  const upload = useCallback(async (file: File) => {
    if (!conversationId) return
    const version = ++request.current
    const draft = { conversationId, name: file.name || '图片', uploading: true }
    setState(draft)
    try {
      const attachment = await uploadImage(conversationId, file)
      if (request.current === version) setState({ ...draft, attachment, uploading: false })
    } catch (error) {
      if (request.current === version) setState({
        ...draft, uploading: false, error: (error as Error).message,
      })
    }
  }, [conversationId, uploadImage])
  const clear = useCallback((attachmentId?: string) => {
    setState((current) => {
      if (attachmentId && current?.attachment?.attachmentId !== attachmentId) return current
      return null
    })
  }, [])
  return {
    image, upload, clear,
    attachmentIds: image?.attachment ? [image.attachment.attachmentId] : [],
  }
}

export function ChatImageButton({
  upload, disabled, uploading,
}: {
  upload: (file: File) => Promise<void>
  disabled: boolean
  uploading?: boolean
}) {
  const ref = useRef<React.ComponentRef<typeof Attachments>>(null)
  return <Attachments ref={ref} accept={imageTypes} disabled={disabled}
    openFileDialogOnClick={false}
    beforeUpload={(file) => { void upload(file); return false }}>
    <SenderAttachButton label="上传图片" disabled={disabled} loading={uploading}
      onClick={() => ref.current?.select()} />
  </Attachments>
}

export function ChatImagePreview({
  image, onRemove, disabled,
}: {
  image: ImageDraft | null
  onRemove: () => void
  disabled?: boolean
}) {
  if (!image || image.error) return null
  const attachment = image.attachment
  return <Attachments style={{ marginBottom: 8 }} disabled={disabled} maxCount={1}
    items={[{
      uid: attachment?.attachmentId ?? 'uploading',
      name: image.name,
      status: image.uploading ? 'uploading' : 'done',
      type: attachment?.mimeType,
      url: attachment ? `/api/customer/attachments/${attachment.attachmentId}/content` : undefined,
    }]}
    onRemove={() => { onRemove(); return true }} />
}

import { FolderOpen } from 'lucide-react'
import { useId, useRef } from 'react'
import { Button } from '@/components/ui/button'

/**
 * The header's "Open session" control - a plain button that proxies to a
 * hidden file input, same trick as any file-picker button. Dropping a file
 * on the page (App.tsx's own drop handlers, same `importFile` underneath)
 * is the other way in - this is for when there's nothing to drag from.
 */
export function OpenSessionButton({ onFile }: { onFile: (file: File) => void }) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => inputRef.current?.click()}
        title="Open a session file (.mppsession.json) exported from this workbench"
      >
        <FolderOpen />
        Open session
      </Button>
      <input
        id={inputId}
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0]
          // Cleared so picking the same filename twice in a row still
          // fires onChange - otherwise a re-import of a fixed file after
          // an error would silently do nothing.
          e.target.value = ''
          if (file) onFile(file)
        }}
      />
    </>
  )
}

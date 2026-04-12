import { Loader2 } from 'lucide-react'

interface Props {
  size?: number
  className?: string
  label?: string
}

export function LoadingSpinner({
  size = 24,
  className = '',
  label,
}: Props) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Loader2
        size={size}
        className="animate-spin text-indigo-600"
        strokeWidth={2.5}
      />
      {label && <span className="text-sm text-slate-600">{label}</span>}
    </div>
  )
}

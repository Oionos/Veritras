import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-[#0a0a0a] px-6 text-[#f0ece4]">
          <h1 className="mb-4 text-2xl font-semibold">Something went wrong</h1>
          <button
            onClick={() => window.location.reload()}
            className="rounded-full bg-linear-to-r from-accent/90 to-accent2/80 px-8 py-3.5 text-sm font-semibold text-bg transition-all hover:scale-[1.02]"
          >
            Reload
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

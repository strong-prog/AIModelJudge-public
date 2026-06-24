import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Panel error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div style={{ padding: "10px", color: "var(--danger)", fontSize: "0.7rem" }}>
            Error: {this.state.error.message}
          </div>
        )
      );
    }
    return this.props.children;
  }
}

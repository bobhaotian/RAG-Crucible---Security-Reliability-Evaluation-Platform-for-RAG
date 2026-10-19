// One panel that throws must not blank the whole run view. React unmounts the
// entire tree on an uncaught render error, so without this a single bad metric
// takes every other panel down with it.

import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class PanelBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`panel "${this.props.title}" failed to render`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <section className="panel panel-error" role="alert">
          <div className="panel-head">
            <h3>{this.props.title}</h3>
          </div>
          <p>
            This panel could not be drawn: <code>{this.state.error.message}</code>. The rest of
            the run is unaffected; the raw metrics are in <code>/runs/&lt;id&gt;/results</code>.
          </p>
        </section>
      );
    }
    return this.props.children;
  }
}

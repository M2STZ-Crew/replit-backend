import { Component } from 'react';

/* A render error anywhere in the console used to unmount the whole page and
 * leave the operator on a blank dark screen. This keeps the error on screen
 * instead: what broke, and two ways out. The message goes to the browser
 * console too, with the component stack, for whoever fixes it. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Admin console crashed:', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="rpl-crash" role="alert">
        <p className="web-eyebrow">Admin console</p>
        <h1 className="web-page-title">This screen stopped working</h1>
        <p className="web-page-description">
          Reload to try again. If it happens again, send the message below to the team.
        </p>
        <pre className="rpl-crash-message">{String(error?.message || error)}</pre>
        <div className="rpl-crash-actions">
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          {this.props.onSignOut && (
            <button type="button" className="rpl-button rpl-button--secondary" onClick={this.props.onSignOut}>
              Sign out
            </button>
          )}
        </div>
      </main>
    );
  }
}

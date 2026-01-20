"""
Log Reader for Debug Agent

Utilities for reading and analyzing prompt logs for debugging workflows.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class PromptLogReader:
    """Reader for prompt execution logs"""

    def __init__(self, log_file: Path):
        """
        Initialize log reader

        Args:
            log_file: Path to the .jsonl log file
        """
        self.log_file = Path(log_file)
        self.entries = []
        self.load()

    def load(self):
        """Load all log entries from file"""
        self.entries = []
        if not self.log_file.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_file}")

        with open(self.log_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    entry = json.loads(line.strip())
                    entry['_line_number'] = line_num
                    self.entries.append(entry)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line {line_num}: {e}")

    def get_all_events(self) -> List[Dict[str, Any]]:
        """Get all log entries"""
        return self.entries

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """
        Get all events of a specific type

        Args:
            event_type: Event type (e.g., 'execution.error', 'node.executing')

        Returns:
            List of matching events
        """
        return [e for e in self.entries if e.get('event') == event_type]

    def get_workflow(self) -> Optional[Dict[str, Any]]:
        """Get the original workflow definition"""
        submitted = self.get_events_by_type('workflow.submitted')
        if submitted:
            return submitted[0].get('workflow')
        return None

    def get_error(self) -> Optional[Dict[str, Any]]:
        """
        Get execution error details if any

        Returns:
            Error entry or None if no error
        """
        errors = self.get_events_by_type('execution.error')
        return errors[0] if errors else None

    def get_executed_nodes(self) -> List[str]:
        """Get list of nodes that executed successfully"""
        executed = self.get_events_by_type('node.executed')
        return [e['node_id'] for e in executed]

    def get_failed_node(self) -> Optional[Dict[str, Any]]:
        """
        Get the node that failed

        Returns:
            Node information or None
        """
        error = self.get_error()
        if error:
            node_id = error.get('error', {}).get('node_id')
            return {
                'node_id': node_id,
                'node_type': error.get('error', {}).get('node_type'),
                'error': error.get('error'),
                'node_context': error.get('node_context')
            }
        return None

    def get_execution_timeline(self) -> List[Dict[str, Any]]:
        """
        Get execution timeline with key events

        Returns:
            List of events in chronological order
        """
        key_events = [
            'workflow.submitted',
            'workflow.queued',
            'websocket.connected',
            'node.executing',
            'node.executed',
            'execution.progress',
            'execution.error',
            'execution.complete',
            'workflow.failed',
            'workflow.success'
        ]

        timeline = []
        for entry in self.entries:
            if entry.get('event') in key_events:
                timeline.append({
                    'timestamp': entry.get('timestamp'),
                    'event': entry.get('event'),
                    'details': self._extract_event_details(entry)
                })
        return timeline

    def _extract_event_details(self, entry: Dict) -> Dict:
        """Extract relevant details from an event"""
        event = entry.get('event')

        if event == 'node.executing':
            return {
                'node_id': entry.get('node_id'),
                'node_type': entry.get('node_class_type')
            }
        elif event == 'node.executed':
            return {'node_id': entry.get('node_id')}
        elif event == 'execution.progress':
            return {
                'progress': f"{entry.get('progress_value')}/{entry.get('progress_max')}",
                'percent': entry.get('progress_percent')
            }
        elif event == 'execution.error':
            error = entry.get('error', {})
            return {
                'node_id': error.get('node_id'),
                'error_type': error.get('exception_type'),
                'error_message': error.get('exception_message')
            }
        return {}

    def get_summary(self) -> Dict[str, Any]:
        """
        Get execution summary

        Returns:
            Summary dict with key information
        """
        error = self.get_error()
        executed_nodes = self.get_executed_nodes()
        workflow = self.get_workflow()

        return {
            'prompt_id': self.entries[0].get('prompt_id') if self.entries else None,
            'server': self.entries[0].get('server') if self.entries else None,
            'total_events': len(self.entries),
            'status': 'failed' if error else 'success',
            'workflow_node_count': len(workflow) if workflow else 0,
            'nodes_executed': len(executed_nodes),
            'executed_nodes': executed_nodes,
            'error': {
                'node_id': error.get('error', {}).get('node_id'),
                'error_type': error.get('error', {}).get('exception_type'),
                'error_message': error.get('error', {}).get('exception_message')
            } if error else None
        }

    def print_summary(self):
        """Print human-readable summary"""
        summary = self.get_summary()

        print(f"\n{'='*60}")
        print(f"Prompt Execution Summary")
        print(f"{'='*60}")
        print(f"Prompt ID: {summary['prompt_id']}")
        print(f"Server: {summary['server']}")
        print(f"Status: {summary['status'].upper()}")
        print(f"Total Events: {summary['total_events']}")
        print(f"Workflow Nodes: {summary['workflow_node_count']}")
        print(f"Nodes Executed: {summary['nodes_executed']}/{summary['workflow_node_count']}")

        if summary['error']:
            print(f"\n{'='*60}")
            print(f"ERROR")
            print(f"{'='*60}")
            print(f"Failed Node: {summary['error']['node_id']}")
            print(f"Error Type: {summary['error']['error_type']}")
            print(f"Error Message: {summary['error']['error_message']}")

        print(f"\n{'='*60}\n")

    def get_websocket_events(self) -> List[Dict[str, Any]]:
        """Get all raw WebSocket events"""
        return [e for e in self.entries if e.get('event', '').startswith('ws.')]

    def export_for_agent(self) -> Dict[str, Any]:
        """
        Export log in format optimized for debug agent

        Returns:
            Dict with structured data for agent analysis
        """
        error = self.get_error()
        failed_node = self.get_failed_node()

        return {
            'summary': self.get_summary(),
            'workflow': self.get_workflow(),
            'timeline': self.get_execution_timeline(),
            'executed_nodes': self.get_executed_nodes(),
            'failed_node': failed_node,
            'error_details': error,
            'all_events': self.get_all_events()
        }


def find_prompt_logs(log_dir: Optional[Path] = None) -> List[Path]:
    """
    Find all prompt log files

    Args:
        log_dir: Directory to search (default: backend/logs/prompts)

    Returns:
        List of log file paths
    """
    if log_dir is None:
        log_dir = Path(__file__).parent / "logs" / "prompts"

    if not log_dir.exists():
        return []

    return sorted(log_dir.glob("*.jsonl"), reverse=True)


def find_failed_prompts(log_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Find all failed prompt executions

    Args:
        log_dir: Directory to search

    Returns:
        List of failed prompt summaries
    """
    failed = []

    for log_file in find_prompt_logs(log_dir):
        try:
            reader = PromptLogReader(log_file)
            summary = reader.get_summary()

            if summary['status'] == 'failed':
                failed.append({
                    'log_file': str(log_file),
                    'summary': summary,
                    'reader': reader
                })
        except Exception as e:
            print(f"Error reading {log_file}: {e}")

    return failed


# Example usage for debug agent
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        log_file = Path(sys.argv[1])
    else:
        # Find most recent failed prompt
        failed = find_failed_prompts()
        if failed:
            log_file = Path(failed[0]['log_file'])
            print(f"Reading most recent failed prompt: {log_file.name}\n")
        else:
            print("No failed prompts found")
            sys.exit(1)

    # Read and analyze log
    reader = PromptLogReader(log_file)
    reader.print_summary()

    # Print timeline
    print("Execution Timeline:")
    print("-" * 60)
    for event in reader.get_execution_timeline():
        timestamp = event['timestamp'].split('T')[1][:12]  # HH:MM:SS.mmm
        print(f"{timestamp} | {event['event']:25} | {event['details']}")

    # Export for agent
    print(f"\n\nLog file: {log_file}")
    print("To analyze with debug agent:")
    print(f"  agent_data = reader.export_for_agent()")

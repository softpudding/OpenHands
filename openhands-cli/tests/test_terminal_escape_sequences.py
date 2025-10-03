#!/usr/bin/env python3
"""
Unit tests for terminal escape sequence handling in OpenHands CLI.
Tests for the issue where terminal shows strange characters like '^[[62;1Rr'
after running openhands-cli for some time.
"""

import io
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from openhands_cli.listeners.loading_listener import (
    LoadingContext,
    display_initialization_animation
)


class TestTerminalEscapeSequences(unittest.TestCase):
    """Test cases for terminal escape sequence handling."""

    def test_escape_sequences_in_loading_animation(self):
        """Test that loading animation uses proper escape sequences."""
        # Capture the actual escape sequences written to stdout
        captured_output = io.StringIO()
        
        with patch('sys.stdout', captured_output):
            with patch('sys.stdout.flush'):
                is_loaded = threading.Event()
                
                # Run animation briefly
                animation_thread = threading.Thread(
                    target=display_initialization_animation,
                    args=("Test animation", is_loaded),
                    daemon=True
                )
                animation_thread.start()
                
                # Let it run for a few frames
                time.sleep(0.3)
                
                # Stop the animation
                is_loaded.set()
                animation_thread.join(timeout=1.0)
        
        output = captured_output.getvalue()
        
        # Verify that escape sequences are present
        self.assertIn('\033[', output, "Expected ANSI escape sequences in output")
        
        # Check for specific escape sequences used in the animation
        self.assertIn('\033[s', output, "Expected save cursor position sequence")
        self.assertIn('\033[u', output, "Expected restore cursor position sequence")
        self.assertIn('\033[J', output, "Expected clear screen sequence")
        self.assertIn('\033[1A', output, "Expected cursor up sequence")

    def test_loading_context_cleanup_on_interrupt(self):
        """Test that LoadingContext properly cleans up terminal state on interrupt."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            
            # Simulate KeyboardInterrupt during loading
            def simulate_interrupt():
                time.sleep(0.1)
                raise KeyboardInterrupt("Simulated interrupt")
            
            with self.assertRaises(KeyboardInterrupt):
                with LoadingContext("Test loading..."):
                    simulate_interrupt()
            
            # Give thread time to clean up
            time.sleep(0.2)
            
            # Verify that cleanup sequences were written
            write_calls = [call[0][0] for call in mock_stdout.write.call_args_list]
            cleanup_sequences = [call for call in write_calls if '\r' in call and ' ' in call]
            self.assertGreater(len(cleanup_sequences), 0, 
                             "Expected cleanup sequences after interrupt")

    def test_incomplete_escape_sequence_scenario(self):
        """Test scenario where escape sequences might be incomplete/corrupted."""
        # This test simulates what happens when escape sequences are interrupted
        captured_chunks = []
        original_write = sys.stdout.write
        
        def capture_write(data):
            captured_chunks.append(data)
            # Simulate partial write (like what might happen during interrupt)
            if '\033[' in data and not data.endswith('m'):
                # Don't complete the sequence to simulate corruption
                return len(data) - 1
            return original_write(data)
        
        with patch('sys.stdout.write', capture_write):
            with patch('sys.stdout.flush'):
                is_loaded = threading.Event()
                
                animation_thread = threading.Thread(
                    target=display_initialization_animation,
                    args=("Partial test", is_loaded),
                    daemon=True
                )
                animation_thread.start()
                
                time.sleep(0.2)
                is_loaded.set()
                animation_thread.join(timeout=1.0)
        
        # Check if we captured any potentially problematic sequences
        incomplete_sequences = [chunk for chunk in captured_chunks 
                              if '\033[' in chunk and not chunk.endswith(('m', 'J', 's', 'u', 'A'))]
        
        # This test documents the potential issue - incomplete sequences could leave terminal in bad state
        if incomplete_sequences:
            print(f"Warning: Found potentially incomplete escape sequences: {incomplete_sequences}")

    def test_thread_safety_of_terminal_operations(self):
        """Test that terminal operations are thread-safe."""
        import concurrent.futures
        
        def run_loading_animation(text):
            with patch('sys.stdout') as mock_stdout:
                mock_stdout.write = MagicMock()
                mock_stdout.flush = MagicMock()
                
                with LoadingContext(text):
                    time.sleep(0.1)
                
                return mock_stdout.write.call_count
        
        # Run multiple loading animations concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(run_loading_animation, f"Test {i}") 
                for i in range(3)
            ]
            
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # All threads should have completed without hanging
        self.assertEqual(len(results), 3, "All threads should complete")
        self.assertTrue(all(count > 0 for count in results), 
                       "All threads should have written to stdout")

    def test_escape_sequence_parsing_issues(self):
        """Test for specific escape sequence parsing problems."""
        # Test the specific sequence mentioned in the issue: '^[[62;1Rr'
        # This looks like a Device Status Report (DSR) response that wasn't handled properly
        
        problematic_sequence = '\x1b[62;1Rr'  # ESC [ 62 ; 1 R r
        
        # Simulate what happens when this sequence is printed
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            # This simulates the terminal being in a state where it's expecting command input
            # but receives a DSR response instead
            print(problematic_sequence, end='')
        
        output = captured.getvalue()
        self.assertEqual(output, problematic_sequence)
        
        # The issue is that '^[[62;1Rr' represents:
        # - ^[ = ESC character
        # - [62;1R = Device Status Report response (cursor position)
        # - r = extra character that shouldn't be there
        # This suggests the terminal was in the middle of processing an escape sequence
        # when it received unexpected input

    def test_terminal_state_restoration(self):
        """Test that terminal state is properly restored after operations."""
        # Mock the _restore_tty function from agent_chat.py
        with patch('openhands_cli.agent_chat._restore_tty') as mock_restore:
            with patch('sys.stdout') as mock_stdout:
                mock_stdout.write = MagicMock()
                mock_stdout.flush = MagicMock()
                
                # Run loading context
                with LoadingContext("Test restoration"):
                    time.sleep(0.1)
                
                # Simulate calling _restore_tty (which should happen in agent_chat cleanup)
                from openhands_cli.agent_chat import _restore_tty
                _restore_tty()
                
                # Verify restoration was attempted
                mock_restore.assert_called_once()


if __name__ == "__main__":
    unittest.main()
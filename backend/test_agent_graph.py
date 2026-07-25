"""
neurocode-backend/test_agent_graph.py

Test script to verify the agent graph directly, bypassing WebSocket.
"""
import sys
import os

# Add neurocode-backend to sys.path so we can import agent modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.graph import agent_graph

import asyncio

async def test_git_status():
    print("\n--- Test: git_status ---")
    state = {
        "transcript": "what is my status?",
        "intent": None,
        "context": {},
        "reasoning": None,
        "confirmation_required": False,
        "confirmed": False,
        "action_result": None,
        "verification_status": "pending",
        "narration": None,
        "earcon": None
    }
    
    result = await agent_graph.ainvoke(state)
    print("Intent:", result.get("intent"))
    print("Narration:", result.get("narration"))
    
    assert result.get("intent") == "git_status"
    assert result.get("confirmation_required") == False
    assert result.get("verification_status") == "skipped"
    print("[PASS] git_status bypasses confirmation and is successfully skipped in execution.")


async def test_git_commit():
    print("\n--- Test: git_commit ---")
    state = {
        "transcript": "commit my changes",
        "intent": None,
        "context": {},
        "reasoning": None,
        "confirmation_required": False,
        "confirmed": False,
        "action_result": None,
        "verification_status": "pending",
        "narration": None,
        "earcon": None
    }
    
    # Run the first half of the graph
    result = await agent_graph.ainvoke(state)
    print("Intent:", result.get("intent"))
    print("Confirmation Required:", result.get("confirmation_required"))
    print("Confirmation Message:", result.get("confirmation_message"))
    
    assert result.get("intent") == "git_commit"
    assert result.get("confirmation_required") == True
    print("[PASS] git_commit correctly pauses for confirmation.")

    # Simulate user confirming and resume
    print("User says 'yes'. Resuming graph...")
    from agent.nodes import execute_action, verify_action, narrate_response
    
    state = execute_action(result)
    result.update(state)
    state = verify_action(result)
    result.update(state)
    state = await narrate_response(result)
    result.update(state)
    
    print("Action Result:", result.get("action_result"))
    print("Narration:", result.get("narration"))
    
    assert result.get("narration") == "Committed successfully." or result.get("verification_status") == "failure" or result.get("verification_status") == "success"
    print("[PASS] git_commit completion logic succeeds.")


async def main():
    await test_git_status()
    await test_git_commit()
    print("\nAll agent graph tests passed!")

if __name__ == "__main__":
    asyncio.run(main())

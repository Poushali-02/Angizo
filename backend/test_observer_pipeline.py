"""
backend/test_observer_pipeline.py

Unit tests for Copilot Observer LLM Prompt Specs 1 and 2 in DiffIntelligence.
"""

import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.diff_intelligence import diff_intelligence

async def test_observer_prompts():
    print("--- Testing Copilot Observer Prompt Specs ---")

    # 1. Test Prompt Spec 1 (copilot_complete summary)
    event_complete = {
        "event_type": "copilot_complete",
        "file": "auth.ts",
        "modified_files": ["auth.ts"],
        "created_files": [],
        "lines_added": 45,
        "lines_removed": 0,
        "error_count": 0,
        "warning_count": 0,
    }
    summary = await diff_intelligence.generate_observer_summary(event_complete)
    print(f"\n[Spec 1 Result - copilot_complete]:\n\"{summary}\"")
    assert len(summary) > 0, "Summary should not be empty"

    # 2. Test Prompt Spec 2 (file_created milestone alert)
    event_file_created = {
        "event_type": "file_created",
        "file": "src/services/payment.py",
    }
    alert_file = await diff_intelligence.generate_observer_summary(event_file_created)
    print(f"\n[Spec 2 Result - file_created]:\n\"{alert_file}\"")
    assert len(alert_file) > 0, "File created alert should not be empty"

    # 3. Test Prompt Spec 2 (dependency_updated milestone alert)
    event_dep_updated = {
        "event_type": "dependency_updated",
        "file": "package.json",
    }
    alert_dep = await diff_intelligence.generate_observer_summary(event_dep_updated)
    print(f"\n[Spec 2 Result - dependency_updated]:\n\"{alert_dep}\"")
    assert len(alert_dep) > 0, "Dependency alert should not be empty"

    print("\n[SUCCESS] All Observer Prompt Spec tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_observer_prompts())

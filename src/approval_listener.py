from types import SimpleNamespace  # Only used to simulate an event for testing

from prompt_toolkit.shortcuts import radiolist_dialog


def approval_listener(event):
    tool_name = event.tool_name
    arguments = event.args

    answer = radiolist_dialog(
        title="Permission required",
        text=f"Tool: {tool_name}\nArguments: {arguments}\n\nDo you approve this action?",
        values=[(True, "Yes"), (False, "No")],
        default=False,
    ).run()

    return answer is True


# Test the listener independently before integrating it into OPHELIA.
# SimpleNamespace is only used to mock a PermissionRequest event for testing.
if __name__ == "__main__":
    test_event = SimpleNamespace(
        id="test_1",
        tool_name="run_bash",
        args={"command": "ls"},
    )

    result = approval_listener(test_event)
    print("Permission granted:", result)

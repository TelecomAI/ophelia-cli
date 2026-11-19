from prompt_toolkit.shortcuts import radiolist_dialog


def approval_listener(tool_name, arguments):
    answer = radiolist_dialog(
        title="Permission required",
        text=f"Tool: {tool_name}\nArguments: {arguments}\n\nDo you approve this action?",
        values=[(True, "Yes"), (False, "No")],
        default=False,
    ).run()

    return answer is True


# Test the listener independently before integrating it into OPHELIA
if __name__ == "__main__":
    result = approval_listener("run_bash", {"command": "rm old_cache.txt"})
    print("Permission granted:", result)

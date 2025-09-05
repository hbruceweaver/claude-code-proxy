# Subagent Tool Registration Issue - Progress Report

## Issue Overview
When Claude Code invokes subagents through the Task tool, the subagents are experiencing tool registration mismatches that cause failures. The model attempts to use tools that aren't available in the request, resulting in validation errors from the backend.

## Root Cause Analysis

### The Problem Flow
1. **Main conversation**: Claude Code sends all 50 tools to the proxy
2. **Subagent invocation**: Claude Code creates a new request with only the tools declared in the agent's `.md` file
3. **Tool mismatch**: The `LS` tool is declared in agent definitions but NOT actually registered by Claude Code CLI
4. **Model confusion**: The subagent's prompt says it has `LS` access, but it's not in the registered tools
5. **Validation failure**: Backend rejects tool calls for `LS` with error: `tool call validation failed: attempted to call tool 'LS' which was not in request.tools`

### Evidence from Logs
```
# What agents declare:
codebase-analyzer: tools: Read, Grep, Glob, LS

# What actually gets registered:
2025-09-05 09:07:01,581 - INFO - Registered 3 tools: Grep, Glob, Read
```

The `LS` tool is consistently missing from actual registrations despite being declared.

## Attempted Solutions

### 1. ❌ Manual Tool Addition in Proxy (Reverted)
- **Approach**: Modified `request_converter.py` to manually add common subagent tools
- **Result**: Not the right approach - proxy should forward what it receives, not modify
- **Status**: Reverted this change

### 2. ❌ Debug Logging
- **Approach**: Added logging to track which tools are registered
- **Result**: Confirmed the mismatch between declared and registered tools
- **Finding**: Claude Code CLI is not sending all declared tools

### 3. ✅ Replace LS with Bash in Agent Definitions
- **Approach**: Since `LS` isn't being registered properly, replace it with `Bash` which can do the same via `ls` command
- **Files Modified**:
  - `/Users/hbruceweaver/.claude/agents/codebase-analyzer.md`
  - `/Users/hbruceweaver/.claude/agents/codebase-locator.md`
  - `/Users/hbruceweaver/.claude/agents/codebase-pattern-finder.md`
  - `/Users/hbruceweaver/.claude/agents/thoughts-analyzer.md`
  - `/Users/hbruceweaver/.claude/agents/thoughts-locator.md`
  - `/Users/hbruceweaver/.claude/agents/web-search-researcher.md`
- **Result**: Partially successful - tools now match declarations

## Current Status

### What's Working
- Tool declarations now match registrations (4 tools: Read, Grep, Glob, Bash)
- No more missing tool errors for properly declared tools
- Proxy correctly forwards whatever tools it receives

### Remaining Issues
1. **Model still attempts to use `Ls`**: Even after removing LS from declarations, the model tried to call `Ls` (with capital L)
   ```
   fastapi.exceptions.HTTPException: 500: tool call validation failed: attempted to call tool 'Ls' which was not in request.tools
   ```

2. **Subagents show "0 tokens" usage**: Subagents appear to fail silently without actually executing
   - Example: `codebase-analyzer` returned "Done (0 tool uses · 0 tokens · 2.9s)"

3. **Context contamination**: The model may have learned about `LS` tool from:
   - Training data
   - Previous conversations
   - System prompts mentioning it

## Next Steps

### Immediate Actions Needed
1. **Search and replace all references to LS/ls in agent prompts**: Not just the tool declarations but also any mentions in the agent instructions
2. **Verify agent prompt templates**: Check if there are hardcoded references to LS tool in the agent markdown files
3. **Test with fresh conversation**: Start new session to avoid context contamination

### Long-term Solutions
1. **Fix in Claude Code CLI**: The CLI should properly register all tools declared in agent definitions
2. **Proxy enhancement**: Add tool validation/correction layer to handle mismatches gracefully
3. **Agent definition validation**: Add checks to ensure declared tools match what's available

## Technical Details

### Key Files
- **Proxy request converter**: `/Users/hbruceweaver/claude-code-proxy/src/conversion/request_converter.py`
- **Agent definitions**: `/Users/hbruceweaver/.claude/agents/*.md`
- **Proxy logs**: `/Users/hbruceweaver/claude-code-proxy/proxy.out`

### Tool Registration Pattern
```python
# Main request: 50 tools including Task
Registered 50 tools: Task, Bash, Glob, Grep, ExitPlanMode, Read, Edit, MultiEdit, Write...

# Subagent request: Limited tools
Registered 4 tools: Read, Grep, Glob, Bash  # After our fix
Registered 3 tools: Grep, Glob, Read        # Before (missing LS)
Registered 2 tools: Grep, Glob              # Some agents
```

## Conclusion
The core issue is a mismatch between what tools subagents declare they have versus what Claude Code CLI actually provides them. We've worked around this by replacing the problematic `LS` tool with `Bash`, but the model still occasionally tries to use `LS/Ls` due to possible context contamination or training data influences.
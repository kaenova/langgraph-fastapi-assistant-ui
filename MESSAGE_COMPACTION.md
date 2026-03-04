Message compaction is a technique for managing conversation state in AI agents by pruning or summarizing message history to fit LLM context limits.

## Core Concept
An agent's state tracks `messages: Message[]`, where each `Message` has `role: 'user' | 'assistant' | 'system'` and `content: string`. Compaction applies a reducer function before LLM calls: `compactedMessages = compact(messages, config)` to shrink total tokens without losing critical intent.  [builder.aws](https://builder.aws.com/content/38oNwLRwQIiQEsuy2eG1KGZ0HR8/message-compaction-with-strands-agents)

## TypeScript Interface
```typescript
interface Message {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  id?: string;
  timestamp?: number;
}

interface CompactionConfig {
  maxTokens: number;      // e.g., 8000
  strategy: 'trim' | 'summary' | 'edit';
  percentile?: number;    // for trim: keep recent N%
}

type CompactionReducer = (
  messages: Message[], 
  config: CompactionConfig
) => Message[] | Promise<Message[]>;
```

## Implementation Strategies

**Trim Strategy** - Keep recent messages by token count:
```typescript
function trimReducer(messages: Message[], config: CompactionConfig): Message[] {
  if (estimateTokens(messages) <= config.maxTokens) return messages;
  
  let tokens = 0;
  const kept: Message[] = [];
  
  // Reverse iterate from newest
  for (let i = messages.length - 1; i >= 0; i--) {
    const msgTokens = estimateTokens(messages[i]);
    if (tokens + msgTokens > config.maxTokens * config.percentile!) {
      break;
    }
    tokens += msgTokens;
    kept.unshift(messages[i]);
  }
  return kept;
}
```

**Summary Strategy** - LLM replaces old history:
```typescript
async function summaryReducer(
  messages: Message[], 
  config: CompactionConfig,
  llm: LLMClient
): Promise<Message[]> {
  if (estimateTokens(messages) <= config.maxTokens) return messages;
  
  const history = messages.slice(0, -5);  // Keep last 5 intact
  const summaryPrompt = `Summarize conversation preserving key facts/decisions:\n${formatMessages(history)}`;
  
  const summary = await llm.generate(summaryPrompt);
  return [{ role: 'system', content: `Summary: ${summary}` }, ...messages.slice(-5)];
}
```

**Edit Strategy** - Remove redundant blocks:
```typescript
function editReducer(messages: Message[]): Message[] {
  return messages.filter(msg => 
    !msg.content.includes('Observation:') &&  // Remove tool observations
    !msg.content.startsWith('Thought:')      // Remove reasoning traces
  );
}
```

## Token Estimation Helper
```typescript
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4) + 3;  // Rough 1 token ≈ 4 chars heuristic
}
```

## Usage Pattern
```typescript
const state = { messages: [] as Message[] };
const reducer: CompactionReducer = config.strategy === 'summary' 
  ? summaryReducer 
  : trimReducer;

state.messages = await reducer(state.messages, config);
// Now safe to pass to LLM
const response = await llm.chat(state.messages);
```

This framework-agnostic approach scales to any agent architecture while staying type-safe.
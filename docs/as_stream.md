# astream_events

> **Method** in `langchain_core`

📖 [View in docs](https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events)

Generate a stream of events.

Use to create an iterator over `StreamEvent` that provide real-time information
about the progress of the `Runnable`, including `StreamEvent` from intermediate
results.

A `StreamEvent` is a dictionary with the following schema:

- `event`: Event names are of the format:
    `on_[runnable_type]_(start|stream|end)`.
- `name`: The name of the `Runnable` that generated the event.
- `run_id`: Randomly generated ID associated with the given execution of the
    `Runnable` that emitted the event. A child `Runnable` that gets invoked as
    part of the execution of a parent `Runnable` is assigned its own unique ID.
- `parent_ids`: The IDs of the parent runnables that generated the event. The
    root `Runnable` will have an empty list. The order of the parent IDs is from
    the root to the immediate parent. Only available for v2 version of the API.
    The v1 version of the API will return an empty list.
- `tags`: The tags of the `Runnable` that generated the event.
- `metadata`: The metadata of the `Runnable` that generated the event.
- `data`: The data associated with the event. The contents of this field
    depend on the type of event. See the table below for more details.

Below is a table that illustrates some events that might be emitted by various
chains. Metadata fields have been omitted from the table for brevity.
Chain definitions have been included after the table.

!!! note
    This reference table is for the v2 version of the schema.

| event                  | name                 | chunk                               | input                                             | output                                              |
| ---------------------- | -------------------- | ----------------------------------- | ------------------------------------------------- | --------------------------------------------------- |
| `on_chat_model_start`  | `'[model name]'`     |                                     | `{"messages": [[SystemMessage, HumanMessage]]}`   |                                                     |
| `on_chat_model_stream` | `'[model name]'`     | `AIMessageChunk(content="hello")`   |                                                   |                                                     |
| `on_chat_model_end`    | `'[model name]'`     |                                     | `{"messages": [[SystemMessage, HumanMessage]]}`   | `AIMessageChunk(content="hello world")`             |
| `on_llm_start`         | `'[model name]'`     |                                     | `{'input': 'hello'}`                              |                                                     |
| `on_llm_stream`        | `'[model name]'`     | `'Hello' `                          |                                                   |                                                     |
| `on_llm_end`           | `'[model name]'`     |                                     | `'Hello human!'`                                  |                                                     |
| `on_chain_start`       | `'format_docs'`      |                                     |                                                   |                                                     |
| `on_chain_stream`      | `'format_docs'`      | `'hello world!, goodbye world!'`    |                                                   |                                                     |
| `on_chain_end`         | `'format_docs'`      |                                     | `[Document(...)]`                                 | `'hello world!, goodbye world!'`                    |
| `on_tool_start`        | `'some_tool'`        |                                     | `{"x": 1, "y": "2"}`                              |                                                     |
| `on_tool_end`          | `'some_tool'`        |                                     |                                                   | `{"x": 1, "y": "2"}`                                |
| `on_retriever_start`   | `'[retriever name]'` |                                     | `{"query": "hello"}`                              |                                                     |
| `on_retriever_end`     | `'[retriever name]'` |                                     | `{"query": "hello"}`                              | `[Document(...), ..]`                               |
| `on_prompt_start`      | `'[template_name]'`  |                                     | `{"question": "hello"}`                           |                                                     |
| `on_prompt_end`        | `'[template_name]'`  |                                     | `{"question": "hello"}`                           | `ChatPromptValue(messages: [SystemMessage, ...])`   |

In addition to the standard events, users can also dispatch custom events (see example below).

Custom events will be only be surfaced with in the v2 version of the API!

A custom event has following format:

| Attribute   | Type   | Description                                                                                               |
| ----------- | ------ | --------------------------------------------------------------------------------------------------------- |
| `name`      | `str`  | A user defined name for the event.                                                                        |
| `data`      | `Any`  | The data associated with the event. This can be anything, though we suggest making it JSON serializable.  |

Here are declarations associated with the standard events shown above:

`format_docs`:

```python
def format_docs(docs: list[Document]) -> str:
    '''Format the docs.'''
    return ", ".join([doc.page_content for doc in docs])

format_docs = RunnableLambda(format_docs)
```

`some_tool`:

```python
@tool
def some_tool(x: int, y: str) -> dict:
    '''Some_tool.'''
    return {"x": x, "y": y}
```

`prompt`:

```python
template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are Cat Agent 007"),
        ("human", "{question}"),
    ]
).with_config({"run_name": "my_template", "tags": ["my_template"]})
```

!!! example

    ```python
    from langchain_core.runnables import RunnableLambda

    async def reverse(s: str) -> str:
        return s[::-1]

    chain = RunnableLambda(func=reverse)

    events = [
        event async for event in chain.astream_events("hello", version="v2")
    ]

    # Will produce the following events
    # (run_id, and parent_ids has been omitted for brevity):
    [
        {
            "data": {"input": "hello"},
            "event": "on_chain_start",
            "metadata": {},
            "name": "reverse",
            "tags": [],
        },
        {
            "data": {"chunk": "olleh"},
            "event": "on_chain_stream",
            "metadata": {},
            "name": "reverse",
            "tags": [],
        },
        {
            "data": {"output": "olleh"},
            "event": "on_chain_end",
            "metadata": {},
            "name": "reverse",
            "tags": [],
        },
    ]
    ```

```python title="Dispatch custom event"
from langchain_core.callbacks.manager import (
    adispatch_custom_event,
)
from langchain_core.runnables import RunnableLambda, RunnableConfig
import asyncio

async def slow_thing(some_input: str, config: RunnableConfig) -> str:
    """Do something that takes a long time."""
    await asyncio.sleep(1) # Placeholder for some slow operation
    await adispatch_custom_event(
        "progress_event",
        {"message": "Finished step 1 of 3"},
        config=config # Must be included for python < 3.10
    )
    await asyncio.sleep(1) # Placeholder for some slow operation
    await adispatch_custom_event(
        "progress_event",
        {"message": "Finished step 2 of 3"},
        config=config # Must be included for python < 3.10
    )
    await asyncio.sleep(1) # Placeholder for some slow operation
    return "Done"

slow_thing = RunnableLambda(slow_thing)

async for event in slow_thing.astream_events("some_input", version="v2"):
    print(event)
```

## Signature

```python
astream_events(
    self,
    input: Any,
    config: RunnableConfig | None = None,
    *,
    version: Literal['v1', 'v2', 'v3'] = 'v2',
    include_names: Sequence[str] | None = None,
    include_types: Sequence[str] | None = None,
    include_tags: Sequence[str] | None = None,
    exclude_names: Sequence[str] | None = None,
    exclude_types: Sequence[str] | None = None,
    exclude_tags: Sequence[str] | None = None,
    **kwargs: Any = {},
) -> AsyncIterator[StreamEvent] | Awaitable[Any]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `input` | `Any` | Yes | The input to the `Runnable`. |
| `config` | `RunnableConfig \| None` | No | The config to use for the `Runnable`. (default: `None`) |
| `version` | `Literal['v1', 'v2', 'v3']` | No | The version of the schema to use. One of `'v1'`, `'v2'`, or `'v3'`.  Most callers should use `'v2'` (the default), which yields `StreamEvent` dicts and supports custom events.  `'v3'` selects the typed, content-block-centric streaming protocol and is only supported on `Runnable` subclasses that implement it (currently `BaseChatModel` and `langgraph.CompiledGraph`); on a generic `Runnable` it raises `NotImplementedError`. The `'v3'` API is in beta and may change. See the subclass override (e.g. `BaseChatModel.astream_events`) for the v3 return shape.  `'v1'` is retained for backwards compatibility and will be deprecated in `0.4.0`. Custom events are only surfaced in `'v2'` / `'v3'`. (default: `'v2'`) |
| `include_names` | `Sequence[str] \| None` | No | Only include events from `Runnable` objects with matching names. (default: `None`) |
| `include_types` | `Sequence[str] \| None` | No | Only include events from `Runnable` objects with matching types. (default: `None`) |
| `include_tags` | `Sequence[str] \| None` | No | Only include events from `Runnable` objects with matching tags. (default: `None`) |
| `exclude_names` | `Sequence[str] \| None` | No | Exclude events from `Runnable` objects with matching names. (default: `None`) |
| `exclude_types` | `Sequence[str] \| None` | No | Exclude events from `Runnable` objects with matching types. (default: `None`) |
| `exclude_tags` | `Sequence[str] \| None` | No | Exclude events from `Runnable` objects with matching tags. (default: `None`) |
| `**kwargs` | `Any` | No | Additional keyword arguments to pass to the `Runnable`. (default: `{}`) |

---

[View source on GitHub](https://github.com/langchain-ai/langchain/blob/8215039dea978372bd3fd95b88663a11b0159043/libs/core/langchain_core/runnables/base.py#L1368)
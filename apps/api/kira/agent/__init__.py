"""The Butler: a LangGraph agent that reaches every module through a tool registry.

Layering is `api → agent → services → engine`. Nothing here imports `kira.api`,
and nothing here writes to a financial table except by way of an approved
`butler_approvals` row.
"""

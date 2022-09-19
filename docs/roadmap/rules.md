# Rules

Set up certain Constraints for yourself


## Structure

The general structure of a rule:
- `name` the name of the rule
- `condition` where to apply it? e.g. only on weekends or only on btc
- `constraint` the actual definition of the rule. which values should be respected?

## Violation
When a rule is violated an event is published. 
This event can be subscribed to through actions in a regular way.
there could be an other mechamism for posting violations to central discord channels of a trading community or a twitter acc.

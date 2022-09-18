# Events

Events are a crucial feature of the platform.
They allow traders to compete in a fair environment,
not dependent on any exchange.

## Technicals

The event service is responsible for firing the lifetime
cycles of events (Registration start, Start, Registration End, End)
and continiuosly updating the scoreboard.

There is always a trade off:

* Updating the leaderboard on benefits small events,
  but slows down big ones, leading to unnecessary requests and updates
* Updating the leaderboard regulary inside a service benefits bigger events,
  bug isn't as performant for smaller events (unnecessary updates)

But however, continous updates have one additional benefit: The load on the system does not wildly
vary as heavily as with an on-demand solution. 



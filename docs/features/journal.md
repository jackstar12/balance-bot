# Journal

Journaling is one of the core features of Trade Alpha.
The system is built in a modular way to suit any kind
of trader.

## Manual

Manual Journals offer basic functionality.
Chapters can be manually created and modified.

## Automatic

Automatic journals are intended for e.g. daily, monthly, weekly journals.
The chapters are automatically created when one of the following
events occur

* the user makes a trade
* the user visits his journal

This comes in handy from a technical perspective because otherwise, the collector would 
have to schedule additional updating jobs. 

## Publication

A user can also choose to share his journal with the public. In this case,
the pages will be prerendered by the frontend and statically served so that no 
extra requests have to be made

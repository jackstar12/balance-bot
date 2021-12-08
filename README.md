# Balance Bot
Discord Bot for showing crypto balances

# Commands
- ## DM Only 
  - ### Register Command
    Registers the user with the given credentials. <br>
    `<prefix> register <exchange> <api secret> <api key> <subaccount> <args...>` <br>
    Some exchanges might require additional arguments, for example: <br>
    `<prefix> register kucoin <api key> <api secret> <subaccount> passphrase=<passphrase>` <br>
    If additional args are given, but there is no subaccount, specify subaccount as 'none'
  - ### Unregister Command  
    Unregisters the user and deletes API access <br>
    `<prefix> unregister`
  - ### Info command
    Shows stored information
    `<prefix> info`
    
- ## Server Commands
  - ### Balance Command 
    Gives current balance of user, the user has to be registered.<br>
    `<prefix> balance @<user>`
  - ### Gain Command  
    Calculates gain of user since given time. Time is passed in through args, for example <br>
    `<prefix> gain <user> 1d 12h` <br>
    If no arguments are passed in, 24h gain will be calculated. <br>
    Supported time arguments:
      - m for minutes
      - h for hours
      - d for days
      - w for weeks
  - ### Leaderboard command
    Fetches data of currently registered users and shows the highest score <br>
    There are 2 modes:
      - balance: Sorts users after their current balance  
      - gain: Sorts users after their gain specified through time args (see gain command).
    
    `<prefix> leaderboard <mode> <args...>`
  - ### History Command
    Graphs user data and sends iamage <br>
    `<prefix> history <user>`
  
  
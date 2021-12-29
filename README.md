# Balance Bot
Discord Bot for showing crypto balances

# Commands
- ## DM Only 
  - ### Register Command
    Registers the user with the given credentials. <br>
    `/register <exchange> <api secret> <api key> <subaccount> <guild> <args...>` <br>
    Some exchanges might require additional arguments, for example: <br>
    `/register exchange: kucoin <api key> <api secret> <subaccount> args: passphrase=<passphrase>` <br>
    If additional args are given, but there is no subaccount, specify subaccount as 'none'
  - ### Unregister Command  
    Unregisters the user and deletes API access <br>
    `/unregister`
  - ### Info command
    Shows stored information
    `/info`
    
- ## Server Commands
  - ### Balance Command 
    Gives current balance of user, the user has to be registered.<br>
    `/balance <user>`
  - ### Gain Command  
    Calculates gain of user since given time. Time is passed in through args, for example <br>
    `/gain <user> time: 1d 12h` <br>
    If no arguments are passed in, 24h gain will be calculated. <br>
    Supported time arguments:
      - m for minutes
      - h for hours
      - d for days
      - w for weeks
  - ### Leaderboard command
    Fetches data of currently registered users and shows the highest score <br>
    There are 2 subommancds:
      - balance sorts users after their current $ balance  
      - gain: Sorts users after their gain specified through time args (see gain command), default since start
  - ### History Command
    Graphs user data onto a plot. You may add another user to compare against. <br>
    from and to are time inputs for start and endpoints of the graph.<br>
    `/history <user> <compare> <from> <to>`
  
  
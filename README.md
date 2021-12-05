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
  - ### Leaderboard command
    Fetches data of currently registered users and shows the highest score <br>
    `<prefix> leaderboard`
  
  
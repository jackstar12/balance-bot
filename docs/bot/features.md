
# Features

## DM Only 
  - ### Register Command
    Registers the user with the given credentials. <br>
    `/register <exchange> <api secret> <api key> <subaccount> <guild> <args...>` <br>
    Some exchanges might require additional arguments, for example: <br>
    `/register exchange: kucoin <api key> <api secret> <subaccount> args: passphrase=<passphrase>` <br>
    If additional args are given, but there is no subaccount, specify subaccount as 'none'
  - ### Unregister Command  
    Unregisters you and deletes all your stored data. <br>
    `/unregister`
  - ### Info command
    Shows stored api information
    `/info`
  - ### Clear command
    Clears your balance history.  <br>
    From and to are time arguments specifying the time range that is being cleared. See [time args](#time-arguments) <br>
    `/clear <from> <to>`
  
## Server Commands
  - ### Balance Command 
    Gives current balance of user, the user has to be registered.<br>
    `/balance <user>`
  - ### Gain Command  
    Calculates gain of user since given time. Time is passed in through args, for example <br>
    `/gain <user> time: 1d 12h` <br>
    If no arguments are passed in, 24h gain will be calculated. See [time args](#time-arguments)
  - ### Leaderboard command
    Fetches data of currently registered users and shows the highest score <br>
    There are 2 subommancds:
      - balance sorts users after their current $ balance  
      - gain: Sorts users after their gain specified through time args (see gain command), default since start
  - ### History Command
    Graphs user data onto a plot. You may add another user to compare against. <br>
    from and to are time inputs for start and endpoints of the graph. See [time args](#time-arguments) <br>
    `/history <user> <compare> <from> <to>`
  
  - ## Time Arguments
    Time args are used in several commands to specify dates and time ranges. <br>
    A time arg can be specified in two formats <br>
    - Relative time <br>`<n><f>` <br>
      where n is an integer and f is either:
        - m for minutes
        - h for hours
        - d for days
        - w for weeks
    
      e.g., `/gain time: 1d 12h` calculates the gain from 1 day and 24 hours ago till now.
    - Absolute time as one of the following date strings:
    
        %H:%M:%S
        %H:%M
        %H
        %d.%m.%Y %H:%M:%S
        %d.%m.%Y %H:%M
        %d.%m.%Y %H
        %d.%m.%Y
        %d.%m. %H:%M:%S
        %d.%m. %H:%M
        %d.%m. %H
        %d.%m.
    
    If the format does not specify the date, the current will be used
    
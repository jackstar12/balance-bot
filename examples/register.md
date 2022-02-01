# How to register

1. Type /register into the chat, you should see a popup like this.

![Register command](register_help.png)

2. Click at the popup or press tab. <br>
   Now type in the parameters.
   - `exchange_name` <br> The name of the exchange you are trading on. <br> 
      Make sure this is one of the provided options.
   - `api_key` 
     <br> The key to your api access. This access should be read-only.
   - `api_secret` <br> The secret to your api access.
   - Optional:
     - `subaccount` <br>
       If you are trading on a subaccount type in the name of it here.
     - `args` <br>
       Right now, this is only used for KuCoin. <br>
       KuCoin requires a passphrase. <br>
       Pass it in through the args option like this: `passphrase=YOUR_PASSPHRASE`

![Example command](help_register_2.jpg)

3. If you typed in everything, press enter. The bot will try to read your balance and 
   then ask you to confirm your registration if no errors occured.
   Now, this should show up:

![Confirmation](help_register_3.jpg)

4. Press yes. You are successfully registered!
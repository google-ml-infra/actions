# CI Connection

This composite step action uses the `wait_for_connection.py` to halt the 
progression of the current workflow for a connection to be received.  It
allows for a customizable period to wait for a connection before
allowing the workflow to resume.  It expects the user to connect via the 
`notify_connection.py` script. If the connection is established, the action
will halt until the user's session ends.

The way in which the user connects to the running machine is out of scope
for this action.

Python3 is required in the running environment for this to work.
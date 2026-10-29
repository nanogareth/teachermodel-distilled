# Request: private store for teachermodel

To: IT ($it_email)
Replies and sign-offs: $mailbox
Reference: [tm-setup it-request]

The technical training function needs one restricted SharePoint document library. It will hold
instructor development records: observations, clearance decisions and coaching notes about named
employees and contractors. This is performance data, so access must be limited to two roles.
Basis: $basis.

## What to set up

1. A dedicated document library named "$library" in the Microsoft 365 tenant. Not a personal
   OneDrive folder: the library must not leave with its owner ($location).
2. One security group for the library. Members: the head of training and the programme
   owner, both with write access. No other user or group gets access to the library ($access).
3. Sharing links turned off for the library, including links for people inside the company ($access).
4. The audit log turned on for the library ($access).
5. Versioning turned on for the library ($backup).
6. A nightly copy of the library to a second company location. Please name the copy target in
   your reply ($backup).

## What we will do

- Sync the library to a path under the user profile on one machine. That machine is the only
  writer of the event log ($location; $one_writer).
- Record the processing in the record of processing activities and ask the data protection
  officer whether a DPIA is needed before any real data is stored ($before_real_data).

## When it is done

Please confirm on the sign-off page we send you that the group exists and the permissions are
set. Name the nightly copy target in the same reply.

## Table of authorities

$authorities

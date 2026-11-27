# Galera replicas apply with eight threads

**Status** — Decided on 2026-11-27, not applied. It is point O3 of section 5.12 of `docs/worldserver-split-research.md` in the `cataclysm-core` repository; the measurements are in that document's appendix M, parts 1 and 5.

The database that the BGS and the realms share is a three-node Galera cluster run by mariadb-operator. Its replicas apply replicated transactions with one thread, the operator's default, because `spec.galera.replicaThreads` is not set. We decided that they apply with eight.

**The setting is not in this chart.** `templates/database.yaml` creates a `MariaDB` only when `database.create` is true, and that one is a single instance without Galera. Production sets `database.create: false` and `mariaDbRef: skymist-db` (`values-production.yaml:2-5`). That resource is defined in the platform's `infra/mariadb.yaml`, which is where `replicaThreads` has to be added. The SkyMist operator also builds a Galera `MariaDB` without the setting, for an installation that provisions its own database (`mariadb` in `skymist_operator/resources.py` of the operator repository). The research document said the setting is in this chart, which is wrong, and this record was filed here on that reading.

What was measured on a scratch cluster shaped like production's, on the three-node production cluster, with a small counter transaction through the primary Service, 16 connections and runs of five minutes:

| Applier threads | Commits per second | Behind a fence row for each writer |
|---|---|---|
| 1, today | 1,086 to 1,097 | 508 to 516 |
| 2 | 821 to 861 | 477 to 486 |
| 4 | 1,707 to 1,870 | 910 to 912 |
| 8 | 3,188 to 3,443 | 1,484 to 1,559 |

- Four and eight are equal up to four connections, at about 1,650. One connection gains nothing at any value (520 to 582).
- Two threads are slower than one. One thread repeated four hours later gave the same figures, so this is not drift.
- In 66 runs and 13.8 million commits the three nodes never diverged, and no saved database log holds an apply error.
- Resident memory did not change with the value: 319 to 344 MiB against a limit of 2 GiB.
- With four threads a deleted primary cost 1.1 seconds of writes and no acknowledged commit.

## Considered Options

- **Four.** Decided first, on three short runs. Equal to eight while four or fewer connections write at once.
- **Sixteen.** Not tested. The ceiling was still rising at eight, where the replicas still paused the writers for three quarters of the time.

## Consequences

- Changing `spec.galera.replicaThreads` makes mariadb-operator restart all three Pods itself, replicas first and the primary last. In five such changes that took 108 to 122 seconds, with 2.5 to 4.4 seconds in which nothing committed and one failed statement for the writer. Afterwards the primary was on another Pod.
- More appliers do not make a read through another node safe. Right after a commit such a read was stale in 57 to 96 % of cases under load, at every value. Every client has to go on using the primary Service, which is what `database.host: skymist-db-primary` gives the BGS (`values-production.yaml:5`).
- Not determined: why the first test measured a lower ceiling at one thread, 570 to 850, than the longer runs did; an unclean loss of a node, a loss of quorum and a full state transfer with parallel appliers; runs longer than five minutes; production's real schema and data volume.

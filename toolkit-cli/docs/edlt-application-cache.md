# Ordered application and group cache

`edlt_application_cache.py` supplies immutable caller-declared lists for the
next explicit model/control phases. It does not yet expose a CLI application
editor, change unit parameters, bind a Toolkit form or query live metadata.

`ApplicationCache` contains existing `LifecycleCache` facts, an ordered tuple
of `CachedDisplay(address, name, formatted_display)` application records,
an explicit `applications_complete` flag, and ordered `CachedGroupList`
records. Each group list has an application address, its own completeness flag
and a tuple of `CachedDisplay` group records. Names and formatted display text
are separate because Toolkit's address/hex display preferences affect the
latter. The schema rejects duplicate numeric identities and contradictory
presence facts; duplicate names and source order are preserved.

`application_choices(primary=..., secondary=...)` requires a complete
application list. It retains addresses 48..127 and 136, excludes the other
stored application, and prepends a distinct `<Unused>` 255 item to the
secondary list. It does not sort, deduplicate names, repair stored selections
or swap the two applications.

`group_choices(application, exclude=..., placeholder=...)` requires that
application's complete ordered group list. It excludes the supplied addresses
and the cached 255 object, then prepends the requested 255 placeholder. An
excluded group remains present in the cache. This is important when an
original role control displays a blank selection for a stored duplicate value.

`group_presence(application, group)` returns `True` or `False` only when a
supplied list or lifecycle fact answers the question. Otherwise it returns
`None`. A partial list is not an empty complete list. Listed group objects can
extend beyond the small set of facts needed by an earlier lifecycle query;
the module never invents dynamic-image or level-cache contents for them.

Five tests pass on Python 3.13.14 and 3.10.20. They cover identity/completeness
validation, all application address boundaries, duplicate names, ordering,
role exclusions, unchanged cache identity and dictionary roundtrips. The
independent [Windows list fixture](../research/fixtures/edlt-application-list-windows-vectors.json)
contains 48 list observations from the original 12-case global-control pilot.
Both primary and secondary choices match at every captured stage. That is
list evidence, not acceptance of application-edit callbacks or full forms.

The upcoming lifecycle extraction and application editor must retain original
widget/scene objects and explicit binding stages. Re-reading these immutable
cache lists does not reproduce a binding callback or justify reloading a PP
snapshot between edits.

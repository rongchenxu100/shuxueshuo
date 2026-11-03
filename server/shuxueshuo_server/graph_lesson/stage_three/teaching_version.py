"""One revision for execution and interaction, shared by photo and topic caches."""

from shuxueshuo_server.problem_understanding.identity import revision


def teaching_revision():
    from . import interaction
    from .runner import fingerprint
    return revision({'execution': fingerprint(), 'interaction_engine': interaction.engine_revision(),
                     'interactions': interaction.registry_revision(interaction.load_registry())})

from django.apps import AppConfig
from django.db.models.signals import post_delete, pre_save


class SubstrappConfig(AppConfig):
    name = 'substrapp'

    def ready(self):
        from .signals.datasample.pre_save import data_sample_pre_save

        from .signals.algo.post_delete import algo_post_delete
        from .signals.objective.post_delete import objective_post_delete
        from .signals.datasample.post_delete import data_sample_post_delete
        from .signals.datamanager.post_delete import datamanager_post_delete
        from .signals.model.post_delete import model_post_delete

        # registering signals with the model's string label
        from substrapp.models import Algo, Objective, DataSample, DataManager, Model

        pre_save.connect(data_sample_pre_save, sender=DataSample)

        post_delete.connect(algo_post_delete, sender=Algo)
        post_delete.connect(objective_post_delete, sender=Objective)
        post_delete.connect(data_sample_post_delete, sender=DataSample)
        post_delete.connect(datamanager_post_delete, sender=DataManager)
        post_delete.connect(model_post_delete, sender=Model)

from rest_framework import serializers, status

from django.conf import settings

from .util import createLedgerTesttuple
from .tasks import createLedgerTesttupleAsync


class LedgerTestTupleSerializer(serializers.Serializer):
    traintuple_key = serializers.CharField(min_length=64, max_length=64)

    def create(self, validated_data):
        traintuple_key = validated_data.get('traintuple_key')
        dataset_key = validated_data.get('dataset_key', '')
        test_data_keys = validated_data.get('test_data_keys', '')

        args = '"%(traintupleKey)s", "%(datasetKey)s", "%(dataKeys)s"' % {
            'traintupleKey': traintuple_key,
            'datasetKey': dataset_key,
            'dataKeys': ','.join([x for x in test_data_keys]),
        }

        if getattr(settings, 'LEDGER_SYNC_ENABLED'):
            return createLedgerTesttuple(args, sync=True)
        else:
            # use a celery task, as we are in an http request transaction
            createLedgerTesttupleAsync.delay(args)

            data = {
                'message': 'The substra network has been notified for adding this Testtuple. Please be aware you won\'t get return values from the ledger. You will need to check manually'
            }
            st = status.HTTP_202_ACCEPTED
            return data, st
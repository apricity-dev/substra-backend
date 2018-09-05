from __future__ import absolute_import, unicode_literals

import os
import tempfile
from os import path

import requests
from django.conf import settings

from substrabac.celery import app
from substrapp.utils import queryLedger, invokeLedger
from .utils import compute_hash


def create_directory(directory):
    if not path.exists(directory):
        os.makedirs(directory)


def get_hash(file):
    with open(file, 'rb') as f:
        data = f.read()
        return compute_hash(data)


def get_computed_hash(url):
    try:
        r = requests.get(url, headers={'Accept': 'application/json;version=0.0'})
    except:
        raise Exception('Failed to check hash due to failed file fetching %s' % url)
    else:
        if r.status_code != 200:
            raise Exception(
                'Url: %(url)s to fetch file returned status code: %(st)s' % {'url': url, 'st': r.status_code})

        computedHash = compute_hash(r.content)

        return r.content, computedHash


def get_challenge_metrics(metrics, pk):
    from substrapp.models import Challenge

    try:
        content, computed_hash = get_computed_hash(metrics['storageAddress'])  # TODO pass cert
    except Exception:
        raise Exception('Failed to fetch description file')
    else:
        if computed_hash != metrics['hash']:
            msg = 'computed hash is not the same as the hosted file. Please investigate for default of synchronization, corruption, or hacked'
            raise Exception(msg)

        try:
            f = tempfile.TemporaryFile()
            f.write(content)

            # save/update challenge in local db for later use
            instance, created = Challenge.objects.update_or_create(pkhash=pk, validated=True)
            instance.metrics.save('metrics.py', f)
        except:
            raise Exception('Failed to save challenge metrics in local db for later use')


def get_algo_file(algo):
    try:
        content, computed_hash = get_computed_hash(algo['storageAddress'])  # TODO pass cert
    except Exception:
        raise Exception('Failed to fetch description file')
    else:
        if computed_hash != algo['hash']:
            msg = 'computed hash is not the same as the hosted file. Please investigate for default of synchronization, corruption, or hacked'
            raise Exception(msg)


def get_model_file(model):
    try:
        content, computed_hash = get_computed_hash(model['storageAddress'])  # TODO pass cert
    except Exception:
        raise Exception('Failed to fetch description file')
    else:
        if computed_hash != model['hash']:
            msg = 'computed hash is not the same as the hosted file. Please investigate for default of synchronization, corruption, or hacked'
            raise Exception(msg)


def fail(key, err_msg):
    # Log Start TrainTest
    data, st = invokeLedger({
        'org': settings.LEDGER['org'],
        'peer': settings.LEDGER['peer'],
        'args': '{"Args":["logFailTrainTest","%(key)s","failed","%(err_msg)s"]}' % {'key': key, 'err_msg': err_msg}
    })

    if st != 201:
        # TODO log error
        pass

    return data


def prepareTask(data_type, status_to_filter, model, status_to_set):
    from shutil import copy
    import zipfile
    from substrapp.models import Challenge, Dataset, Data, Model, Algo

    try:
        data_owner = get_hash(settings.LEDGER['signcert'])
    except Exception as e:
        pass
    else:
        traintuples, st = queryLedger({
            'org': settings.LEDGER['org'],
            'peer': settings.LEDGER['peer'],
            'args': '{"Args":["queryFilter","traintuple~trainWorker~status","%s,%s"]}' % (data_owner, status_to_filter)
        })

        if st == 200:
            for traintuple in traintuples:
                # check if challenge exists and its metrics is not null
                challengeHash = traintuple['challenge']['hash']
                try:
                    challenge = Challenge.objects.get(pk=challengeHash)
                except:
                    # get challenge metrics
                    try:
                        get_challenge_metrics(traintuple['challenge']['metrics'], challengeHash)
                    except Exception as e:
                        return fail(traintuple['key'], e)
                else:
                    if not challenge.metrics:
                        # get challenge metrics
                        try:
                            get_challenge_metrics(traintuple['challenge']['metrics'], challengeHash)
                        except Exception as e:
                            return fail(traintuple['key'], e)

                ''' get algo + model '''
                # get algo file
                try:
                    get_algo_file(traintuple['algo'])
                except Exception as e:
                    return fail(traintuple['key'], e)

                # get model file
                try:
                    get_model_file(traintuple[model])
                except Exception as e:
                    return fail(traintuple['key'], e)

                # create a folder named traintuple['key'] im /medias/traintuple with 4 folders opener, data, model, pred
                directory = path.join(getattr(settings, 'MEDIA_ROOT'), 'traintuple/%s' % traintuple['key'])
                create_directory(directory)
                folders = ['opener', 'data', 'model', 'pred']
                for folder in folders:
                    directory = path.join(getattr(settings, 'MEDIA_ROOT'),
                                          'traintuple/%s/%s' % (traintuple['key'], folder))
                    create_directory(directory)

                # put opener file in opener folder
                try:
                    dataset = Dataset.objects.get(pk=traintuple[data_type]['openerHash'])
                except Exception as e:
                    return fail(traintuple['key'], e)
                else:
                    data_opener_hash = get_hash(dataset.data_opener.path)
                    if data_opener_hash != traintuple[data_type]['openerHash']:
                        return fail(traintuple['key'], 'DataOpener Hash in Traintuple is not the same as in local db')

                    copy(dataset.data_opener.path,
                         path.join(getattr(settings, 'MEDIA_ROOT'), 'traintuple/%s/%s' % (traintuple['key'], 'opener')))

                # same for each train/test data
                for data_key in traintuple[data_type]['keys']:
                    try:
                        data = Data.objects.get(pk=data_key)
                    except Exception as e:
                        return fail(traintuple['key'], e)
                    else:
                        data_hash = get_hash(data.file.path)
                        if data_hash != data_key:
                            return fail(traintuple['key'],
                                        'Data Hash in Traintuple is not the same as in local db')

                        to_directory = path.join(getattr(settings, 'MEDIA_ROOT'),
                                                 'traintuple/%s/%s' % (traintuple['key'], 'data'))
                        copy(data.file.path, to_directory)
                        # unzip files
                        zip_file_path = os.path.join(to_directory, os.path.basename(data.file.name))
                        zip_ref = zipfile.ZipFile(zip_file_path, 'r')
                        zip_ref.extractall(to_directory)
                        zip_ref.close()
                        os.remove(zip_file_path)

                # same for model
                try:
                    model = Model.objects.get(pk=traintuple[model]['hash'])
                except Exception as e:
                    return fail(traintuple['key'], e)
                else:
                    model_file_hash = get_hash(model.file.path)
                    if model_file_hash != traintuple[model]['hash']:
                        return fail(traintuple['key'], 'Model Hash in Traintuple is not the same as in local db')

                    copy(model.file.path,
                         path.join(getattr(settings, 'MEDIA_ROOT'), 'traintuple/%s/%s' % (traintuple['key'], 'model')))

                # put algo to root
                try:
                    algo = Algo.objects.get(pk=traintuple['algo']['hash'])
                except Exception as e:
                    return fail(traintuple['key'], e)
                else:
                    algo_file_hash = get_hash(algo.file.path)
                    if algo_file_hash != traintuple['algo']['hash']:
                        return fail(traintuple['key'], 'Algo Hash in Traintuple is not the same as in local db')

                    copy(algo.file.path,
                         path.join(getattr(settings, 'MEDIA_ROOT'), 'traintuple/%s' % (traintuple['key'])))

                # do not put anything in pred folder

                # Log Start TrainTest with status_to_set
                data, st = invokeLedger({
                    'org': settings.LEDGER['org'],
                    'peer': settings.LEDGER['peer'],
                    'args': '{"Args":["logStartTrainTest","%s","%s"]}' % (traintuple['key'], status_to_set)
                })

                if st != 201:
                    # TODO log error
                    pass

                # TODO log success


@app.task
def prepareTrainingTask():
    prepareTask('trainData', 'todo', 'startModel', 'training')
    # TODO launch training task


@app.task
def prepareTestingTask():
    prepareTask('testData', 'trained', 'endModel', 'testing')
    # TODO launch testing task

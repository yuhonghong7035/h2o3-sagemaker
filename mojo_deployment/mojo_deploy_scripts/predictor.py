"""
Adapted from https://github.com/awslabs/amazon-sagemaker-examples/blob/master/advanced_functionality/scikit_bring_your_own/container/decision_trees/predictor.py

This is the file that implements a flask server to do inference

Flask isn't necessarily the most optimal way to do this because H2O can give
you a POJO which you can then use with any Java server, which might give you
much better performance than Flask. That said, this is for a proof of concept
that it's possible to integrate H2O AutoML with Amazon Sagemaker, and it's
reasonably safe to assume for this purpose that the volume of inference
requests is going to be low enough that flask can handle them just fine
"""


import flask
import h2o
import os
# import socket
# import time
import pandas as pd
from io import StringIO
from h2o.exceptions import H2OError


# This is where our training script saves the model that was generated
prefix = '/opt/ml/'
model_path = os.path.join(prefix, 'model')

# print("Creating Connection to Mojo REST Server")
# h2o_launched = False
# i = 0
# while h2o_launched is False:
#     try:
#         s = socket.socket()
#         s.connect(("127.0.0.1", 8080))
#         h2o_launched = True
#     except Exception as e:
#         time.sleep(6)
#         if i % 5 == 0:
#             print("Attempt {}: H2O-3 not running yet...".format(i))
#         if i > 30:
#             raise Exception("""Could not connect to Mojo REST Server in {} attempts
#                                Last Error: {}""".format(i, e))
#         i += 1
#     finally:
#         s.close()


class ScoringService(object):
    model = None                # Where we keep the model when it's loaded

    @classmethod
    def get_model(cls):
        """Get the model object for this instance,
        loading it if it's not already loaded."""
        if cls.model is None:
            for file in os.listdir(model_path):
                # Assumes that 'AutoML' is somewhere in the filename of a
                # model that's been generated. We just load the first model
                # that satisfies this constraint, so caveat emptor if you've
                # run the 'train' script multiple times - this may still load
                # the first model. An obvious to-do is to improve this :-)
                if 'mojo' in file:
                    os.system("rm -rf /opt/h2oai/dai/mojo-pipeline")
                    os.system("cp -r {} /opt/h2oai/dai".format(os.path.join(model_path, file)))
                    break
        return True

    @classmethod
    def import_data_from_csv(cls, data_file=""):
        try:
            h2o_prediction_frame = h2o.import_file(data_file)
            return h2o_prediction_frame
        except H2OError as e:
            print("Error: {}".format(e))
            print("Trying to fall back to pandas")

        try:
            data = pd.read_csv(data_file)
            data.columns = data.columns.astype(str)
            h2o_prediction_frame = h2o.H2OFrame(data)
            return h2o_prediction_frame
        except Exception as e:
            raise Exception("Error: {}, could not import data".format(e))

    @classmethod
    def export_data_to_csv(cls, h2o_frame, export_path=""):
        try:
            h2o.export_file(h2o_frame, export_path)
            return export_path
        except H2OError as e:
            print("Error: {}".format(e))
            print("Trying to fall back to pandas")

        try:
            df = h2o_frame.as_data_frame(use_pandas=True, header=True)
            df.to_csv(export_path, header=True)
            return export_path
        except Exception as e:
            raise Exception("Error: {}, could not export data".format(e))

    @classmethod
    def predict(cls, input_data, data_type, model_path):
        """
        Predict class and generate probabilities based on test data

        This is essentially the function that's doing inference. The test data
        is assumed to be in a H2OFrame, and also has the same columns as the
        train/validation data

        :param input: H2OFrame that contains data to make predictions on
        :return: Predictions for each row in the H2OFrame. This returns the
        predicted class, as well as the probabilities of it belonging to a
        specific class
        """
        clf = cls.get_model()
        print("TYPE OF INPUT: {}, VARIABLE. {}".format(type(input_data), input_data))
        # df = pd.DataFrame(input_data)
        # df.to_csv('/opt/ml/output/output.csv')
        os.system("java -Dai.h2o.mojos.runtime.license.file={}/mojo-pipeline/license.sig \
                   -cp {}/mojo-pipeline/mojo2-runtime.jar ai.h2o.mojos.ExecuteMojo \
                   {}/mojo-pipeline/pipeline.mojo \
                   {}".format(model_path, model_path, model_path, input_data))
        return "/opt/ml/output/output.csv"


# The flask app for serving predictions
app = flask.Flask(__name__)


@app.route('/ping', methods=['GET'])
def ping():
    """Determine if the container is working and healthy.
    In this sample container, we declare it healthy if we can load the
    model successfully."""

    health = ScoringService.get_model() is not None  # Reasonable health check

    status = 200 if health else 404
    return flask.Response(response='\n', status=status,
                          mimetype='application/json')


@app.route('/invocations', methods=['POST'])
def transformation():
    """
    Method that actually does inference on a batch of data

    This function does something along the lines of:
    CSV data from flask -> Pandas -> H2OFrame -> H2oAutoML.predict(H2OFrame)

    Results are finally returned as a CSV back to the server
    """

    if flask.request.content_type == 'file/csv':
        data_type = 'file/csv'
        data = flask.request.data.decode('utf-8')
        s = StringIO(data)
        data = pd.read_csv(s)
        data.to_csv("/opt/predict.csv")
        print("Invoked with {} records".format(data.shape[0]))

    else:
        raise Exception("Request Not Properly Formatted to CSV")


    # Do the actual prediction using the AutoML model that's been loaded
    predictions = ScoringService.predict("/opt/predict.csv", data_type, model_path)
    out = StringIO()
    results = pd.read_csv(predictions)
    results.to_csv(out, header=True)
    result = out.getvalue()

    return flask.Response(response=result, status=200, mimetype='text/csv')

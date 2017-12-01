# Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#     http://www.apache.org/licenses/LICENSE-2.0
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

# coding: utf-8
from .import_onnx import GraphProto
import mxnet as mx
import numpy as np
from onnx.backend.base import Backend, BackendRep
from collections import namedtuple

# Using these functions for onnx test infrastructure.
# Implemented by following onnx docs guide:
# https://github.com/onnx/onnx/blob/master/docs/Implementing%20an%20ONNX%20backend.md
# MXNetBackend class will take an ONNX model with inputs, perform a computation,
# and then return the output.
# MXNetBackendRep object will be returned by MXNetBackend's prepare method which is used to
# execute a model repeatedly.
# We will pass inputs to the run function of MXNetBackendRep to retrieve the corresponding results.

class MXNetBackend(Backend):
    @classmethod
    def run_node(cls, node, inputs, device='CPU'):
        """Running individual node inference on mxnet engine and
        return the result to onnx test infrastructure.

        Parameters
        ----------
        node  : onnx node object
            loaded onnx node (individual layer)
        inputs : numpy array
            input to run on operator on

        Returns
        -------
        params : numpy array
            result obtained after running the operator
        """
        graph = GraphProto()
        sym = graph.run_node(node)
        data_names = [i for i in node.input]
        data_shapes = []

        # Adding extra dimension of batch_size 1 if the batch_size is different for multiple inputs.
        for idx, input_name in enumerate(data_names):
            batch_size = 1L
            if len(inputs[idx].shape) < 4 and len(inputs) > 1 and len(set(x.shape[0] for x in inputs)) != 1:
                tuples = ((batch_size,), inputs[idx].shape)
                new_shape = sum(tuples, ())
                data_shapes.append((input_name, new_shape))
            else:
                data_shapes.append((input_name, inputs[idx].shape))

        # create a module
        mod = mx.mod.Module(symbol=sym, data_names=data_names, label_names=None)
        mod.bind(for_training=False, data_shapes=data_shapes, label_shapes=None)

        # initializing parameters for calculating result of each individual node
        mod.init_params()

        Batch = namedtuple('Batch', ['data'])

        data_forward = []
        for val in inputs:
            # slice and pad operator tests needs 1 less dimension in forward pass
            # otherwise it will throw an error.
            if node.op_type == 'Slice' or node.op_type == 'Pad':
                data_forward.append(mx.nd.array(val))
            else:
                data_forward.append(mx.nd.array([val]))

        mod.forward(Batch(data_forward))
        result = mod.get_outputs()[0].asnumpy()
        if node.op_type == 'Slice' or node.op_type == 'Pad':
            return [result]
        return result

    @classmethod
    def prepare(cls, model, device='CPU', **kwargs):
        """For running end to end model(used for onnx test backend)

        Parameters
        ----------
        model  : onnx ModelProto object
            loaded onnx graph
        device : 'CPU'
            specifying device to run test on

        Returns
        -------
        MXNetBackendRep : object
            Returns object of MXNetBackendRep class which will be in turn
            used to run inference on the input model and return the result for comparison.
        """
        graph = GraphProto()
        sym, params = graph.from_onnx(model.graph)
        return MXNetBackendRep(sym, params)

    @classmethod
    def supports_device(cls, device):
        """Supports only CPU for testing"""
        return device == 'CPU'


class MXNetBackendRep(BackendRep):
    """Running model inference on mxnet engine and return the result
     to onnx test infrastructure for comparison."""
    def __init__(self, symbol, params):
        self.symbol = symbol
        self.params = params

    def run(self, inputs, **kwargs):
        """Run model inference and return the result

        Parameters
        ----------
        inputs : numpy array
            input to run on operator on

        Returns
        -------
        params : numpy array
            result obtained after running the inference on mxnet
        """
        input_data = np.asarray(inputs[0], dtype=np.float32)
        # create module
        mod = mx.mod.Module(symbol=self.symbol, data_names=['input_0'], context=mx.cpu(), label_names=None)
        mod.bind(for_training=False, data_shapes=[('input_0', input_data.shape)], label_shapes=None)
        mod.set_params(arg_params=self.params, aux_params=None)

        # run inference
        Batch = namedtuple('Batch', ['data'])

        mod.forward(Batch([mx.nd.array(input_data)]))
        result = mod.get_outputs()[0].asnumpy()
        return [result]

prepare = MXNetBackend.prepare

run_node = MXNetBackend.run_node

supports_device = MXNetBackend.supports_device

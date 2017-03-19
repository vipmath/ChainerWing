import chainer

from lib.node import Input, Loss
from lib.util import ExistsInvalidParameter


class SoftmaxCrossEntropy(Loss):
    Input('in_array', chainer.Variable)

    def call(self):
        return 'softmax_cross_entropy(self.y, t)'


class SigmoidCrossEntropy(Loss):
    Input('in_array', chainer.Variable)

    def call(self):
        return 'sigmoid_cross_entropy(self.y, t)'


class MeanSquaredError(Loss):
    Input('in_array', chainer.Variable)

    def call(self):
        return 'mean_squared_error(self.y, t)'


class HuberLoss(Loss):
    Input('in_array', chainer.Variable)
    Input('delta', float)

    def call(self):
        if hasattr(self, '_delta'):
            raise ExistsInvalidParameter(self.ID, '_delta')
        return 'huber_loss(self.y, t, delta={0})'.format(self._delta)

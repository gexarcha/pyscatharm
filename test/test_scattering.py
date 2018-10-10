""" This script will test the submodules used by the scattering module"""

import torch
import unittest
import numpy as np
from scatharm.filters_bank import gaussian_3d, solid_harmonic_filters_bank
from scatharm.scattering import SolidHarmonicScattering
from scatharm import utils as sl

def linfnorm(x,y):
    return torch.max(torch.abs(x-y))

class TestScattering(unittest.TestCase):
    def testFFT3dCentralFreqBatch(self):
        # Checked the 0 frequency for the 3D FFT
        for gpu in [False, True]:
            x = torch.FloatTensor(1, 32, 32, 32, 2).fill_(0)
            if gpu:
                x = x.cuda()

            a = x.sum()
            fft3d = sl.Fft3d()
            y = fft3d(x)
            c = y[:,0,0,0].sum()
            self.assertAlmostEqual(a, c, places=6)

    def testSumOfGaussianFFT3d(self):
        # Check the validity of Fourier transform of sum of gaussians
        _N = 128
        M, N, O = _N, _N, _N
        sigma = 2.
        n_gaussians = 10
        np_grid = np.fft.ifftshift(
            np.mgrid[-M//2:-M//2+M, -N//2:-N//2+N, -O//2:-O//2+O].astype('float32'), axes=(1,2,3))
        np_fourier_grid = np_grid.copy()
        np_fourier_grid[0] *= 2*np.pi / M
        np_fourier_grid[1] *= 2*np.pi / N
        np_fourier_grid[2] *= 2*np.pi / O
        grid = torch.from_numpy(np_grid)
        grid_gpu = grid.cuda()
        fourier_grid = torch.from_numpy(np_fourier_grid)
        fourier_grid_gpu = fourier_grid.cuda()

        positions = torch.FloatTensor(1, n_gaussians, 3).uniform_(-0.5 * _N + 5*sigma, 0.5 * _N - 5*sigma)
        positions[...,2].fill_(0)
        weights = torch.FloatTensor(1, n_gaussians).uniform_(1, 10)

        fft3d = sl.Fft3d()

        for gpu in [False, True]:
            if gpu:
                _grid = grid_gpu
                _fourier_grid = fourier_grid_gpu
            else:
                _grid = grid
                _fourier_grid = fourier_grid
            sum_of_gauss = sl.generate_weighted_sum_of_gaussians(
                _grid, positions, weights, sigma, cuda=gpu)
            sum_of_gauss_fourier = sl.generate_weighted_sum_of_gaussians_in_fourier_space(
                _fourier_grid, positions, weights, sigma, cuda=gpu)
            sum_of_gauss_ = fft3d(sum_of_gauss_fourier, inverse=True, normalized=True)[..., 0]
            self.assertAlmostEqual(torch.norm(sum_of_gauss - sum_of_gauss_), 0, places=5)


    def testSolidHarmonicFFT3d(self):
        # test that solid harmonic fourier inverse fourier transform corresponds to the formula
        M, N, O = 192, 128, 96
        sigma, J, L = 3., 0, 1
        solid_harmonics = solid_harmonic_filters_bank(M, N, O, J, L, sigma, fourier=False)
        solid_harmonics_fourier = solid_harmonic_filters_bank(M, N, O, J, L, sigma, fourier=True)
        fft3d = sl.Fft3d()
        for gpu in [False, True]:
            for l in range(L+1):
                for m in range(2*l+1):
                    solid_harm = solid_harmonics[l][0:1,m]
                    solid_harm_fourier = solid_harmonics_fourier[l][0:1,m]
                    if gpu:
                        solid_harm = solid_harm.cuda()
                        solid_harm_fourier = solid_harm_fourier.cuda()
                    solid_harm_ = fft3d(solid_harm_fourier, inverse=True, normalized=True)
                    self.assertAlmostEqual(torch.norm(solid_harm - solid_harm_), 0, places=7)


    def testSolidHarmonicScattering(self):
        # Compare value to analytical formula in the case of a single Gaussian
        centers = torch.FloatTensor(1, 1, 3).fill_(0)
        weights = torch.FloatTensor(1, 1).fill_(1)
        sigma_gaussian = 3.
        sigma_0_wavelet = 3.
        M, N, O, J, L = 128, 128, 128, 1, 4
        grid = torch.from_numpy(
            np.fft.ifftshift(np.mgrid[-M//2:-M//2+M, -N//2:-N//2+N, -O//2:-O//2+O].astype('float32'), axes=(1,2,3)))
        x = sl.generate_weighted_sum_of_gaussians(grid, centers, weights, sigma_gaussian)
        scat = SolidHarmonicScattering(M=M, N=N, O=O, J=J, L=L, sigma_0=sigma_0_wavelet)
        args = {'integral_powers': [1]}
        s_order_0, s_order_1 = scat(x, order_2=False, method='integral', method_args=args)

        for j in range(J+1):
            sigma_wavelet = sigma_0_wavelet*2**j
            k = sigma_wavelet / np.sqrt(sigma_wavelet**2 + sigma_gaussian**2)
            for l in range(1, L+1):
                self.assertAlmostEqual(s_order_1[0, 0, j, l], k**l, places=4)


    def testLowPassFilter(self):
        # Test convolution of gaussian with a gaussian
        centers = torch.FloatTensor(1, 1, 3).fill_(0)
        weights = torch.FloatTensor(1, 1).fill_(1)
        sigma_gaussian = 3.
        sigma_0_wavelet = 3.
        M, N, O, J, L = 128, 128, 128, 2, 0
        grid = torch.from_numpy(
            np.fft.ifftshift(np.mgrid[-M//2:-M//2+M, -N//2:-N//2+N, -O//2:-O//2+O].astype('float32'), axes=(1,2,3)))
        x = torch.FloatTensor(1, M, N, O, 2).fill_(0)
        x[..., 0] = sl.generate_weighted_sum_of_gaussians(grid, centers, weights, sigma_gaussian)
        scat = SolidHarmonicScattering(M=M, N=N, O=O, J=J, L=L, sigma_0=sigma_0_wavelet)

        for j in range(J+1):
            convolved_gaussian = scat._low_pass_filter(x, j)

            sigma_convolved_gaussian = np.sqrt(sigma_gaussian**2 + (sigma_0_wavelet*2**j)**2)
            true_convolved_gaussian = torch.FloatTensor(1, M, N, O, 2).fill_(0)
            true_convolved_gaussian[0, ..., 0] = torch.from_numpy(gaussian_3d(M, N, O, sigma_convolved_gaussian, fourier=False))

            diff = torch.norm(convolved_gaussian - true_convolved_gaussian)
            self.assertAlmostEqual(diff, 0, places=5)


if __name__ == '__main__':
    unittest.main()

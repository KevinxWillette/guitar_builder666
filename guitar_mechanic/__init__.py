"""Guitar Mechanic — automated enhancer, slicer, scaler, and populator.

Drop raw photos of guitar components into the ``uploads/`` folder and the
mechanic works on them: it cleans the image up, cuts the part out of its
background, scales it to real-world proportions, and files it into the
component library ready for the guitar builder.
"""

__version__ = "0.1.0"

from .mechanic import Mechanic  # noqa: F401

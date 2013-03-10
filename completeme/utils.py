import json
import logging
import os

import pkg_resources

_logger = logging.getLogger(__name__)

class ComputationInterruptedException(Exception):
    pass

class UNINITIALIZED(object):
    def __init__(self):
        raise NotImplementedError("Don't use this class for reals.  It's a sentinel.")

CONFIG_FN = pkg_resources.resource_filename(__name__, "conf/completeme.json")
def get_config(key, default="NO_DEFAULT"):
    """ Returns the value for the config key, loading first from the working directory and then the basic install point.  Can be overridden with CONFIG_FN environment variable. """

    def load_config():
        CONFIG_CACHE_KEY = "cached_config"
        if hasattr(get_config, CONFIG_CACHE_KEY):
            return getattr(get_config, CONFIG_CACHE_KEY)

        base_fn = os.path.basename(CONFIG_FN)
        fn_paths = [ os.path.join("conf", base_fn),
                     CONFIG_FN ]
        if "CONFIG_FN" in os.environ:
            fn_paths.append(os.environ["CONFIG_FN"])

        for fn in fn_paths:
            try:
                cfg = json.load(open(fn, "r"))
                setattr(get_config, CONFIG_CACHE_KEY, cfg)
                _logger.debug("Loaded config at {:s}.".format(fn))
                return cfg
            except IOError:
                pass

        raise Exception("Couldn't load config from any of {}".format(fn_paths))

    return load_config()[key] if default == "NO_DEFAULT" else load_config().get(key, default)

def split_search_dir_and_query(input_str):
    """ Given an input_str, deduce what directory we should search, either by relative path (../../whatever) or by absolute path (/). """

    # first, expand any user tildes or whatever (~/whatever, ~user/whatever)
    dirname = os.path.expanduser(input_str)
    query = ""
    is_first = True # the whole input string must end in a slash to be checked for a directory

    # now, peel off directories until we find one that matches
    while dirname:
        if (os.path.isdir(dirname) and (not is_first or dirname.endswith("/"))):
            # we've found a directory that exists!  search here
            return os.path.abspath(dirname), query

        # peel back one directory, like an onion!
        dirname, fn = os.path.split(dirname)
         # prepend to the query
        query = os.path.join(fn, query) if query != "" else fn
        is_first = False

    # fall back to current directory
    return os.path.abspath("."), query
